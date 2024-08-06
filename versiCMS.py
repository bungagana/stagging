import asyncio
from io import BytesIO
from PIL import Image as load_image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, CallbackContext
import google.generativeai as genai
import json
from dotenv import load_dotenv
import os
import string
from nltk.tokenize import word_tokenize
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
import mysql.connector
from datetime import datetime, timedelta
from telegram.ext import JobQueue
from nltk.corpus import stopwords
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
import time

load_dotenv()
TELEGRAM_TOKEN = '7312741064:AAFk_W5SwLydq9oP14gyQXSPPzAtLCmFOLA'
API_KEY = os.getenv('API_KEY')

generation_config = {
    "temperature": 0.1,  # Lower temperature for less randomness
    "top_p": 0.8,        # Lower top_p for more deterministic output
    "top_k": 20,         # Lower top_k for more deterministic output
    "max_output_tokens": 500,
}

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-1.0-pro", generation_config=generation_config
)

#--- load dataset ---
with open('data_training.json', 'r') as file:
    dataTraining = json.load(file)
#-- track user aktif  + kasih sesi---
user_last_activity = {}
INACTIVITY_THRESHOLD = timedelta(hours=1)

def update_user_activity(user_id, chat_id):
    user_last_activity[user_id] = datetime.now()
    connection = get_db_connection()
    if connection is None:
        return
    cursor = connection.cursor()
    try:
        query = "SELECT * FROM userTele WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        result = cursor.fetchone()
        if result is None:
            query = "INSERT INTO userTele (user_id, chat_id) VALUES (%s, %s)"
            cursor.execute(query, (user_id, chat_id))
        else:
            query = "UPDATE userTele SET last_activity = NOW() WHERE user_id = %s"
            cursor.execute(query, (user_id,))
        connection.commit()
    except mysql.connector.Error as err:
        print(f"Error: {err}")
    finally:
        cursor.close()
        connection.close()
        
# Function to handle the /start command
# async def start(update: Update, context):
#     user = update.effective_user
#     update_user_activity(user.id)
#     await context.bot.send_message(chat_id=update.effective_chat.id,
#                                    text=f"Hi {user.mention_html()}!\n\nStart sending messages with me to generate a response.\n\nSend /new to start a new chat session.",
#                                    parse_mode=ParseMode.HTML)
# Function to handle the /start command
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    chat_id = update.effective_chat.id
    update_user_activity(user.id, chat_id)
    start_text = (
        f"Hi {user.mention_html()}!\n\n"
        "Start sending messages with me to generate a response.\n\n"
        "Send /new to start a new chat session.\n\n"
        "For more information on how to interact with the bot, use the /help command."
    )
    await context.bot.send_message(chat_id=chat_id, text=start_text, parse_mode=ParseMode.HTML)
    await help_command(update, context)

#-- Help Command ---
async def help_command(update: Update, context: CallbackContext):
    help_text = (
        "Saya adalah bot informasi dosen. Anda dapat menggunakan perintah berikut untuk mencari informasi mengenai dosen:\n\n"
        "- <b>List dosen prodi [nama prodi]</b>: Menampilkan daftar dosen untuk program studi tertentu. Contoh: <code>List dosen prodi Teknik Informatika</code>\n"
        "- <b>Kode dosen [kode]</b>: Menampilkan informasi dosen berdasarkan kode dosen. Contoh: <code>Kode dosen ABC123</code>\n"
        "- <b>Peminatan dosen [nama dosen]</b>: Menampilkan peminatan dosen berdasarkan nama. Contoh: <code>Peminatan dosen Budi Santoso</code>\n"
        "- <b>No telepon dosen [nama dosen]</b>: Menampilkan nomor telepon dosen berdasarkan nama. Contoh: <code>No telepon dosen Budi Santoso</code>\n"
        "- <b>Email dosen [nama dosen]</b>: Menampilkan email dosen berdasarkan nama. Contoh: <code>Email dosen Budi Santoso</code>\n"
        "- <b>NIDN dosen [nama dosen]</b>: Menampilkan NIDN dosen berdasarkan nama. Contoh: <code>NIDN dosen Budi Santoso</code>\n"
        "- <b>Ruangan dosen [nama dosen]</b>: Menampilkan ruangan dosen berdasarkan nama. Contoh: <code>Ruangan dosen Budi Santoso</code>\n"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text, parse_mode=ParseMode.HTML)

async def newchat_command(update: Update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    update_user_activity(user_id, chat_id)
    context.chat_data["chat"] = model.start_chat(history=dataTraining)
    await update.message.reply_text(text="New chat session started.")

def format_message(message):
    return message

#-- Get ref dari respon dataset ---
def get_reference_response(question):
    question_lower = question.strip().lower()
    for idx, entry in enumerate(dataTraining):
        if entry['role'] == 'user' and entry['parts'][0].strip().lower() == question_lower:
            if idx + 1 < len(dataTraining) and dataTraining[idx + 1]['role'] == 'model':
                return dataTraining[idx + 1]['parts']
    return [""]

def preprocess_text(text, label=""):
    print(f"{label} Before Processing: {text}")
    text = text.lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    tokens = word_tokenize(text)
    stop_words = set(stopwords.words('indonesian'))
    tokens = [token for token in tokens if token not in stop_words]
    print(f"{label} Processed text: {' '.join(tokens)}")
    print(f"{label} Tokens: {tokens} \n")
    
    return tokens

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='chatbot',
            port=3308
        )
        return connection
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

def get_lecturer_info(name):
    connection = get_db_connection()
    if connection is None:
        return []
    cursor = connection.cursor(dictionary=True)
    query = "SELECT * FROM dosen WHERE nama_lengkap LIKE %s"
    cursor.execute(query, (f"%{name}%",))
    result = cursor.fetchall()
    cursor.close()
    connection.close()
    return result

def get_lecturer_info_by_code(kode_dosen):
    connection = get_db_connection()
    if connection is None:
        return []
    cursor = connection.cursor(dictionary=True)
    query = "SELECT * FROM dosen WHERE kode_dosen = %s"
    cursor.execute(query, (kode_dosen,))
    result = cursor.fetchall()
    cursor.close()
    connection.close()
    return result

def get_lecturer_info_by_prodi(prodi):
    connection = get_db_connection()
    if connection is None:
        return []
    cursor = connection.cursor(dictionary=True)
    query = "SELECT * FROM dosen WHERE prodi LIKE %s"
    cursor.execute(query, (f"%{prodi}%",))
    result = cursor.fetchall()
    cursor.close()
    connection.close()
    return result

async def button_click(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data.startswith("detail_dosen_"):
        kode_dosen = data.split("_")[-1]
        lecturers = get_lecturer_info_by_code(kode_dosen)
        if lecturers:
            lecturer = lecturers[0]  
            response_text = f"Dosen: {lecturer['nama_lengkap']}\nNIDN: {lecturer['nidn']}\nNo Telepon: {lecturer['no_telepon']}\nEmail: {lecturer['email']}\nRuangan: {lecturer['ruangan']}\nPeminatan: {lecturer['peminatan']}\nProdi: {lecturer['prodi']}"
        else:
            response_text = "Informasi mengenai dosen tidak ditemukan."

        await context.bot.send_message(chat_id=query.message.chat_id,
                                       text=response_text,
                                       parse_mode=ParseMode.HTML)
    else:
        await query.answer("Tombol ini belum diimplementasikan.")
        
async def handle_text_message(update: Update, context):
    try:
        start_time = time.time()  # Start time measurement
        
        text = update.message.text
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        update_user_activity(user_id, chat_id)

        preprocessed_question = preprocess_text(text, label="Question")

        if text.lower().startswith('list dosen'):
            prodi = text.split('prodi')[-1].strip()
            lecturers = get_lecturer_info_by_prodi(prodi)
            
            if lecturers:
                response_text = "List Dosen:\n\n"
                keyboard = []
                for lecturer in lecturers:
                    button_text = f"{lecturer['nama_lengkap']} ({lecturer['kode_dosen']})"
                    button_callback = f"detail_dosen_{lecturer['kode_dosen']}"
                    keyboard.append([InlineKeyboardButton(text=button_text, callback_data=button_callback)])
                    response_text += f"• {lecturer['nama_lengkap']}\n"
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_message(chat_id=update.effective_chat.id,
                                               text=response_text,
                                               reply_markup=reply_markup,
                                               parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id,
                                               text=f"Tidak ada dosen yang tersedia untuk program {prodi}.",
                                               parse_mode=ParseMode.HTML)
            end_time = time.time()  
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return
        
        if 'kode dosen' in text.lower():
            kode_dosen = text.split('kode dosen')[-1].strip()
            lecturers = get_lecturer_info_by_code(kode_dosen)
            if lecturers:
                response_text = "\n".join([f"NIDN: {lecturer['nidn']}, Dosen: {lecturer['nama_lengkap']}, No Telepon: {lecturer['no_telepon']}, Ruangan: {lecturer['ruangan']}, Peminatan: {lecturer['peminatan']}, Kode Dosen: {lecturer['kode_dosen']}, Email: {lecturer['email']}, Prodi: {lecturer['prodi']}" for lecturer in lecturers])
            else:
                response_text = "Kode Dosen Tersebut Tidak Tersedia di Database"
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=response_text,
                                           parse_mode=ParseMode.HTML)
            end_time = time.time()  
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return

        if 'peminatan dosen' in text.lower():
            name = text.split('dosen')[-1].strip()
            lecturers = get_lecturer_info(name)
            if lecturers:
                response_text = "\n".join([f"Peminatan: {lecturer['peminatan']}, Dosen: {lecturer['nama_lengkap']}" for lecturer in lecturers])
            else:
                response_text = "Nama Dosen Tersebut Tidak Tersedia di Database"
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=response_text,
                                           parse_mode=ParseMode.HTML)
            end_time = time.time() 
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return

        if 'no telepon dosen' in text.lower():
            name = text.split('dosen')[-1].strip()
            lecturers = get_lecturer_info(name)
            if lecturers:
                response_text = "\n".join([f"No Telepon: {lecturer['no_telepon']}, Dosen: {lecturer['nama_lengkap']}" for lecturer in lecturers])
            else:
                response_text = "Nama Dosen Tersebut Tidak Tersedia di Database"
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=response_text,
                                           parse_mode=ParseMode.HTML)
            end_time = time.time() 
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return
        
        if 'email dosen' in text.lower():
            name = text.split('dosen')[-1].strip()
            lecturers = get_lecturer_info(name)
            if lecturers:
                response_text = "\n".join([f"Email: {lecturer['email']}, Dosen: {lecturer['nama_lengkap']}" for lecturer in lecturers])
            else:
                response_text = "Nama Dosen Tersebut Tidak Tersedia di Database"
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=response_text,
                                           parse_mode=ParseMode.HTML)
            end_time = time.time() 
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return
        
        if 'nidn dosen' in text.lower():
            name = text.split('dosen')[-1].strip()
            lecturers = get_lecturer_info(name)
            if lecturers:
                response_text = "\n".join([f"NIDN: {lecturer['nidn']}, Dosen: {lecturer['nama_lengkap']}" for lecturer in lecturers])
            else:
                response_text = "Nama Dosen Tersebut Tidak Tersedia di Database"
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=response_text,
                                           parse_mode=ParseMode.HTML)
            end_time = time.time() 
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return
        
        if 'ruangan dosen' in text.lower():
            name = text.split('dosen')[-1].strip()
            lecturers = get_lecturer_info(name)
            if lecturers:
                response_text = "\n".join([f"Ruangan: {lecturer['ruangan']}, Dosen: {lecturer['nama_lengkap']}" for lecturer in lecturers])
            else:
                response_text = "Nama Dosen Tersebut Tidak Tersedia di Database"
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text=response_text,
                                           parse_mode=ParseMode.HTML)
            end_time = time.time() 
            response_time = end_time - start_time
            print(f"Response Time: {response_time:.2f} seconds")
            return
        
        if context.chat_data.get("chat") is None:
            context.chat_data["chat"] = model.start_chat(history=dataTraining)
        
        response = await context.chat_data["chat"].send_message_async(text, stream=True)
        full_plain_message = ""
        async for chunk in response:
            if chunk.text:
                full_plain_message += chunk.text
        message = format_message(full_plain_message)
        
        preprocessed_answer = preprocess_text(message, label="Answer")
        
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=message,
                                       parse_mode=ParseMode.HTML)
        
        #-- BLEU SCORE + TIME LLMS ---
        reference = get_reference_response(text)
        if reference:
            candidate_tokens = preprocessed_answer
            reference_tokens = [preprocess_text(ref, label="Reference") for ref in reference]
            smoothie = SmoothingFunction().method1
            bleu_score = sentence_bleu(reference_tokens, candidate_tokens, smoothing_function=smoothie)

            # Detailed BLEU score (kalkukasi)
            def n_grams(sequence, n):
                return [tuple(sequence[i:i+n]) for i in range(len(sequence)-n+1)]

            def compute_bleu(candidate, references, n):
                candidate_ngrams = n_grams(candidate, n)
                reference_ngrams = [n_grams(ref, n) for ref in references]
                reference_ngrams_flat = set([item for sublist in reference_ngrams for item in sublist])
                matches = sum(1 for ngram in candidate_ngrams if ngram in reference_ngrams_flat)
                possible_matches = len(candidate_ngrams)
                precision = matches / possible_matches if possible_matches > 0 else 0
                return precision

            print(f"Question: {text}")
            print(f"Expected: {reference}")
            print(f"Candidate: {message}")
            print(f"Candidate Tokens: {candidate_tokens}")
            print(f" ========================")
            for n in range(1, 5):
                precision = compute_bleu(candidate_tokens, reference_tokens, n)
                print(f"{n}-gram precision: {precision}")
            print(f" ========================")
            print(f"BLEU Score: {bleu_score}\n")
        else:
            print("No reference response found for the given question.")
        
        end_time = time.time() 
        response_time = end_time - start_time
        print(f"Response Time: {response_time:.2f} seconds")
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        await context.bot.send_message(chat_id=update.effective_chat.id,
                                       text=f"An error occurred: {str(e)}",
                                       parse_mode=ParseMode.HTML)

#--- Buat handle img ----
async def handle_image(update: Update, context):
    images = update.message.photo
    unique_images = {}
    for img in images:
        file_id = img.file_id[:-7]
        if file_id not in unique_images:
            unique_images[file_id] = img
        elif img.file_size > unique_images[file_id].file_size:
            unique_images[file_id] = img
    file_list = list(unique_images.values())
    file = await file_list[0].get_file()
    await context.bot.send_message(chat_id=update.effective_chat.id,
                                   text="Image received. However, I cannot process images at the moment.",
                                   parse_mode=ParseMode.HTML)

# -- reminder session tidak aktif --
async def check_inactivity(context: CallbackContext):
    now = datetime.now()
    for user_id, last_activity in list(user_last_activity.items()):
        if now - last_activity > INACTIVITY_THRESHOLD:
            await context.bot.send_message(chat_id=user_id,
                                           text="You have been inactive for a while. Here are some commands to help you get started:\n\n/start - Start the bot\n/help - Get help. Shows this message\n/new - Start a new chat session\n\nTo ask about lecturers, you can use the following formats:\n- 'List dosen prodi [nama prodi]'\n- 'Kode dosen [kode]'\n- 'Peminatan dosen [nama dosen]'\n- 'No telepon dosen [nama dosen]'\n- 'Email dosen [nama dosen]'\n- 'NIDN dosen [nama dosen]'\n- 'Ruangan dosen [nama dosen]'",
                                           parse_mode=ParseMode.HTML)
            user_last_activity.pop(user_id, None)

# Add command handlers
application = Application.builder().token(TELEGRAM_TOKEN).build()

button_click_handler = CallbackQueryHandler(button_click)
application.add_handler(button_click_handler)

start_handler = CommandHandler('start', start)
application.add_handler(start_handler)

help_handler = CommandHandler('help', help_command)
application.add_handler(help_handler)

newchat_handler = CommandHandler('new', newchat_command)
application.add_handler(newchat_handler)

# Add text message handler
text_message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
application.add_handler(text_message_handler)

# Add image handler
image_handler = MessageHandler(filters.PHOTO, handle_image)
application.add_handler(image_handler)

# Job to check for inactive users every hour
job_queue = application.job_queue
job_queue.run_repeating(check_inactivity, interval=3600, first=0)

application.run_polling()