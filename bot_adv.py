import os
import logging
import google.generativeai as genai
import openai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from pymongo import MongoClient
from serpapi import GoogleSearch
from PIL import Image
import spacy
from transformers import pipeline


load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
MONGO_URI = os.getenv("MONGO_URI")

nlp = spacy.load("en_core_web_sm")

sentiment_analyzer = pipeline("sentiment-analysis")
summarizer = pipeline("summarization")

client = MongoClient(MONGO_URI)
db = client["TelegramBotDB"]
users_collection = db["Users"]
collection = db["ChatHistory"]

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")
gemini_vision_model = genai.GenerativeModel("gemini-1.5-flash")
openai.api_key = OPENAI_API_KEY

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    name = update.message.from_user.full_name

    if users_collection.find_one({"user_id": user_id}):
        await update.message.reply_text("Welcome back! Type /profile to view your details.")
    else:
        user_data = {
            "user_id": user_id,
            "username": username,
            "name": name,
            "registration_date": datetime.utcnow(),
            "preferences": {}
        }
        users_collection.insert_one(user_data)
        await update.message.reply_text(f"Hello {name}! 🎉 You are now registered.")

async def view_profile(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user = users_collection.find_one({"user_id": user_id})

    if user:
        profile_text = (
            f"👤 **Profile Info:**\n"
            f"📌 Name: {user['name']}\n"
            f"📌 Username: @{user['username']}\n"
            f"📌 Registered on: {user['registration_date'].strftime('%Y-%m-%d')}\n"
        )
        await update.message.reply_text(profile_text)
    else:
        await update.message.reply_text("You are not registered! Type /start to register.")


async def chat_with_ai(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_text = update.message.text

    response = chat_gemini(user_text)

    chat_data = {
        "user_id": user_id,
        "user_message": user_text,
        "bot_response": response
    }
    collection.insert_one(chat_data)

    await update.message.reply_text(response)

def process_nlp(text):
    doc = nlp(text)

    entities = [(ent.text, ent.label_) for ent in doc.ents]

    sentiment = sentiment_analyzer(text)[0]
    
    keywords = [token.text for token in doc if token.pos_ in ["NOUN", "PROPN"]]

    summary = ""
    if len(text.split()) > 50:  # Only summarize if long text
        summary = summarizer(text, max_length=50, min_length=20, do_sample=False)[0]["summary_text"]

    return {
        "entities": entities,
        "sentiment": sentiment,
        "keywords": keywords,
        "summary": summary,
    }

async def analyze_text(update: Update, context: CallbackContext):
    user_text = " ".join(context.args)
    if not user_text:
        await update.message.reply_text("⚠️ Please provide text to analyze. Example: `/analyze I love AI`")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)

    nlp_results = process_nlp(user_text)

    response_text = (
        f"🔍 **Entities:** {nlp_results['entities']}\n"
        f"😊 **Sentiment:** {nlp_results['sentiment']['label']} ({nlp_results['sentiment']['score']:.2f})\n"
        f"📌 **Keywords:** {', '.join(nlp_results['keywords'])}\n"
    )
    
    if nlp_results["summary"]:
        response_text += f"📖 **Summary:** {nlp_results['summary']}"

    await update.message.reply_text(response_text)

def chat_gemini(prompt):
    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        logging.error(f"Gemini Error: {e}")
        return "Gemini AI couldn't process your request."

async def analyze_image(update: Update, context: CallbackContext):
    photo = update.message.photo[-1] 
    file = await photo.get_file()
    file_path = "received_image.jpg"
    await file.download_to_drive(file_path)

    response = process_image(file_path)

    await update.message.reply_text(response)

def process_image(image_path):
    try:
        img = Image.open(image_path)
        response = gemini_vision_model.generate_content(["Describe this image:", img])
        return response.text

        image_data = {
        "user_id": user_id,
        "user_message": user_text,
        "bot_response": response
    }

    except Exception as e:
        return f"Error analyzing image: {e}"


async def search_web(update: Update, context: CallbackContext):
    query = " ".join(context.args)
    
    if not query:
        await update.message.reply_text("Usage: /search <query>")
        return

    try:
        params = {
            "q": query,
            "api_key": SERPAPI_KEY,
            "engine": "google",
            "num": 5
        }
        search = GoogleSearch(params)
        results = search.get_dict()

        # Extract top 5 links
        if "organic_results" in results:
            links = [f"{i+1}. {res['title']}\n{res['link']}" for i, res in enumerate(results["organic_results"][:5])]
            response = "\n\n".join(links)
        else:
            response = "No results found."

    except Exception as e:
        logging.error(f"Search Error: {e}")
        response = "Error performing web search."

    await update.message.reply_text(response)

async def get_history(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    history = collection.find({"user_id": user_id}).limit(5)

    if history:
        response = "\n\n".join([f"You: {chat['user_message']}\nBot: {chat['bot_response']}" for chat in history])
    else:
        response = "No chat history found."

    await update.message.reply_text(response)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", view_profile)) 
    app.add_handler(CommandHandler("search", search_web))
    app.add_handler(CommandHandler("analyze", analyze_text))
    app.add_handler(CommandHandler("history", get_history))
    app.add_handler(MessageHandler(filters.PHOTO, analyze_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_with_ai))

    logging.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
