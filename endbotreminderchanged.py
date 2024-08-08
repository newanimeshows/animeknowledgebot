import os
import requests
import sqlite3
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext
import asyncio
import re
from flask import Flask
from threading import Thread
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler, BaseHTTPRequestHandler








# Your Telegram bot token
TOKEN = os.getenv('BOT_TOKEN')  # Replace with your actual token

# List of websites to search
WEBSITES = [
    'https://graphql.anilist.co',
    'https://kitsu.io/api/edge'
]

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            user_id INTEGER,
            anime_name TEXT,
            remind_time TEXT,
            PRIMARY KEY (user_id, anime_name, remind_time)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_interaction TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Initialize SQLite database for welcome messages
def init_welcome_db():
    try:
        conn = sqlite3.connect('welcome.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS welcome_status (
                user_id INTEGER PRIMARY KEY,
                last_welcome_date TEXT
            )
        ''')
        conn.commit()
        conn.close()
        print("SQLite database initialized successfully.")
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        
# Function to check if user has already been welcomed today
def has_been_welcomed_today(user_id):
    try:
        conn = sqlite3.connect('welcome.db')
        cursor = conn.cursor()
        cursor.execute('SELECT last_welcome_date FROM welcome_status WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            last_welcome_date = datetime.strptime(result[0], '%Y-%m-%d').date()
            today = date.today()
            return last_welcome_date == today
        else:
            return False
    except sqlite3.Error as e:
        print(f"SQLite error in has_been_welcomed_today(): {e}")
        return False

# Function to update welcome status
def update_welcome_status(user_id):
    try:
        conn = sqlite3.connect('welcome.db')
        cursor = conn.cursor()
        today = date.today().isoformat()  # Get today's date in ISO format
        cursor.execute('INSERT OR REPLACE INTO welcome_status (user_id, last_welcome_date) VALUES (?, ?)', (user_id, today))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"SQLite error in update_welcome_status(): {e}")
        
def add_reminder(user_id, anime_name, remind_time):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO reminders (user_id, anime_name, remind_time) VALUES (?, ?, ?)',
                   (user_id, anime_name, remind_time))
    conn.commit()
    conn.close()

def remove_reminder(user_id, anime_name):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reminders WHERE user_id = ? AND anime_name = ?', (user_id, anime_name))
    conn.commit()
    conn.close()

def show_reminders(user_id):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('SELECT anime_name, remind_time FROM reminders WHERE user_id = ?', (user_id,))
    reminders = cursor.fetchall()
    conn.close()
    return reminders

# Add favorite anime to the database with the English title
def add_favorite(user_id, anime_name, english_title=None):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    # Use either english_title or anime_name
    title_to_store = english_title if english_title else anime_name
    cursor.execute('INSERT OR IGNORE INTO favorites (user_id, anime_name) VALUES (?, ?)', (user_id, title_to_store))
    conn.commit()
    conn.close()

def remove_favorite(user_id, anime_name, english_title=None):
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    if english_title:
        cursor.execute('DELETE FROM favorites WHERE user_id = ? AND anime_name = ?', (user_id, english_title))
    else:
        cursor.execute('DELETE FROM favorites WHERE user_id = ? AND anime_name = ?', (user_id, anime_name))
    conn.commit()
    conn.close()



async def remind_me(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if len(context.args) < 2:
        await update.message.reply_text("Please provide valid Name and Time. \n\nUsage: /remind <anime_name> <time_in_minutes>")
        return
    
    anime_name = context.args[0]
    try:
        remind_in = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Please provide a valid time in minutes.")
        return
    
    remind_time = (datetime.now() + timedelta(minutes=remind_in)).isoformat()
    add_reminder(user_id, anime_name, remind_time)
    await update.message.reply_text(f"Reminder set for '{anime_name}' in {remind_in} minutes.")

async def show_reminders_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    reminders = show_reminders(user_id)
    if reminders:
        reminder_list = '\n'.join([f"{anime} at {time}" for anime, time in reminders])
        await update.message.reply_text(f"Your reminders:\n{reminder_list}")
    else:
        await update.message.reply_text("You have no reminders set.")

async def remove_reminder_command(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /removereminder <anime_name>")
        return
    
    anime_name = context.args[0]
    remove_reminder(user_id, anime_name)
    await update.message.reply_text(f"Removed reminder for '{anime_name}'.")

async def check_reminders():
    now = datetime.now().isoformat()
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, anime_name FROM reminders WHERE remind_time <= ?', (now,))
    reminders = cursor.fetchall()
    conn.close()
    
    bot = Bot(token=TOKEN)  # Initialize the bot object

    for user_id, anime_name in reminders:
        try:
            await bot.send_message(chat_id=user_id, text=f"Reminder: It's time to watch '{anime_name}'!")
        except Exception as e:
            print(f"Error sending reminder to user {user_id}: {e}")

    # Remove reminders that have been sent
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reminders WHERE remind_time <= ?', (now,))
    conn.commit()
    conn.close()

# Retrieve favorite anime for a user
async def get_favorites(user_id: int) -> list:
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('SELECT anime_name FROM favorites WHERE user_id = ?', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    # Filter out None values and return non-None anime names
    return [row[0] for row in rows if row[0] is not None]


def fetch_anime_data(query):
    url = 'https://graphql.anilist.co'
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, json={'query': query}, headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

def get_weekly_top_anime():
    query = '''
    {
      Page {
        media(sort: POPULARITY_DESC, type: ANIME, season: WINTER, seasonYear: 2024) {
          title {
            romaji
            english
          }
          id
        }
      }
    }
    '''
    data = fetch_anime_data(query)
    if data and 'data' in data and 'Page' in data['data']:
        return data['data']['Page']['media']
    return None

def get_trending_anime():
    query = '''
    {
      Page {
        media(sort: TRENDING_DESC, type: ANIME) {
          title {
            romaji
            english
          }
          id
        }
      }
    }
    '''
    data = fetch_anime_data(query)
    if data and 'data' in data and 'Page' in data['data']:
        return data['data']['Page']['media']
    return None

def get_top_anime_list():
    query = '''
    {
      Page {
        media(sort: SCORE_DESC, type: ANIME) {
          title {
            romaji
            english
          }
          id
        }
      }
    }
    '''
    data = fetch_anime_data(query)
    if data and 'data' in data and 'Page' in data['data']:
        return data['data']['Page']['media']
    return None

def search_anime(query):
    results = []
    query_lower = query.lower()

    for website in WEBSITES:
        if website == 'https://graphql.anilist.co':
            search_url = website
            query_data = {'query': f'''
                query {{
                  Page {{
                    media(search: "{query}", type: ANIME) {{
                      title {{
                        romaji
                        english
                      }}
                      id
                    }}
                  }}
                }}
            '''}
        elif website == 'https://kitsu.io/api/edge':
            search_url = f"{website}/anime?filter[name]={query.replace(' ', '+')}"

        try:
            if website == 'https://graphql.anilist.co':
                response = requests.post(search_url, json=query_data)
            else:
                response = requests.get(search_url, timeout=10)

            if response.status_code == 200:
                if website == 'https://graphql.anilist.co':
                    data = response.json()
                    for media in data['data']['Page']['media']:
                        title = media['title']['romaji']
                        results.append({'title': title, 'id': media['id']})
                elif website == 'https://kitsu.io/api/edge':
                    data = response.json()
                    for anime in data['data']:
                        title = anime['attributes']['canonicalTitle']
                        results.append({'title': title, 'id': anime['id']})

        except Exception as e:
            print(f"Error fetching from {website}: {e}")

    if results:
        sorted_results = sorted(results, key=lambda x: x['title'])
        return sorted_results
    return None

async def weekly(update: Update, context: CallbackContext) -> None:
    data = get_weekly_top_anime()
    if data:
        keyboard = [[InlineKeyboardButton(anime['title']['romaji'], callback_data=f'detail_{anime["id"]}')] for anime in data[:7]]
        keyboard.append([InlineKeyboardButton("Back to Main Menu", callback_data='start')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Weekly Top Anime:\n"
        if update.message:
            await update.message.reply_text(text=message, reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text(text=message, reply_markup=reply_markup)
    else:
        if update.message:
            await update.message.reply_text("No data available.")
        else:
            await update.callback_query.message.reply_text("No data available.")

async def trending(update: Update, context: CallbackContext) -> None:
    data = get_trending_anime()
    if data:
        keyboard = [[InlineKeyboardButton(anime['title']['romaji'], callback_data=f'detail_{anime["id"]}')] for anime in data[:10]]
        keyboard.append([InlineKeyboardButton("Back to Main Menu", callback_data='start')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Trending Anime:\n"
        if update.message:
            await update.message.reply_text(text=message, reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text(text=message, reply_markup=reply_markup)
    else:
        if update.message:
            await update.message.reply_text("No data available.")
        else:
            await update.callback_query.message.reply_text("No data available.")

async def top(update: Update, context: CallbackContext) -> None:
    data = get_top_anime_list()
    if data:
        keyboard = [[InlineKeyboardButton(anime['title']['romaji'], callback_data=f'detail_{anime["id"]}')] for anime in data[:10]]
        keyboard.append([InlineKeyboardButton("Back to Main Menu", callback_data='start')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Top Anime List:\n"
        if update.message:
            await update.message.reply_text(text=message, reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text(text=message, reply_markup=reply_markup)
    else:
        if update.message:
            await update.message.reply_text("No data available.")
        else:
            await update.callback_query.message.reply_text("No data available.")

async def search(update: Update, context: CallbackContext) -> None:
    query = ' '.join(context.args) if context.args else ''
    if not query:
        if update.message:
            await update.message.reply_text("Please provide a anime name. \n\n/search <animename>")
        else:
            await update.callback_query.message.reply_text("Please provide a anime name. \n\n/search <animename>")
        return

    results = search_anime(query)
    if results:
        keyboard = [[InlineKeyboardButton(anime['title'], callback_data=f'detail_{anime["id"]}')] for anime in results]
        keyboard.append([InlineKeyboardButton("Back to Main Menu", callback_data='start')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text("Embark on an anime adventure: Choose your title for detailed insights.", reply_markup=reply_markup)
        else:
            await update.callback_query.message.reply_text("Embark on an anime adventure: Choose your title for detailed insights.", reply_markup=reply_markup)
    else:
        if update.message:
            await update.message.reply_text("No search results found.")
        else:
            await update.callback_query.message.reply_text("No search results found.")

async def details(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    anime_id = query.data.split('_')[1]

    query_details = f'''
    {{
      Media(id: {anime_id}) {{
        title {{
          romaji
          english
        }}
        description
        coverImage {{
          extraLarge
        }}
        episodes
        season
        seasonYear
        genres
      }}
    }}
    '''
    data = fetch_anime_data(query_details)
    
    if data and 'data' in data and 'Media' in data['data']:
        anime = data['data']['Media']
        title = anime['title']['romaji']
        english_title = anime['title']['english']
        description = anime['description']

        # Remove <br> and <i> tags from description
        description = re.sub(r'<br\s*?/?>', '', description)  # Replace <br> or <br/> with newline
        description = re.sub(r'<i\s*?>|</i>', '', description)  # Remove <i> and </i> tags

        cover_image = anime['coverImage']['extraLarge']
        episodes = anime['episodes']
        season = anime['season']
        season_year = anime['seasonYear']
        genres = ', '.join(anime['genres'])

        message = (f"*Title:* {title}\n\n"
                   f"*English Title:* {english_title}\n\n"
                   f"*Description:* {description}\n"
                   f"*Episodes:* {episodes}\n"
                   f"*Season:* {season} {season_year}\n"
                   f"*Genres:* {genres}\n"
                   f"[Cover Image]({cover_image})")

        keyboard = [
            [InlineKeyboardButton("Add to Favorites", callback_data=f'addfav_{anime_id}')],
            [InlineKeyboardButton("Remove from Favorites", callback_data=f'removefav_{anime_id}')],
            [InlineKeyboardButton("Search Again", callback_data='search')],
            [InlineKeyboardButton("Back to Main Menu", callback_data='start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(text=message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await query.message.reply_text("Details not found.")

async def add_favorite_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    anime_id = query.data.split('_')[1]
    user_id = query.from_user.id

    # Fetch anime details to get the English title
    query_details = f'''
    {{
      Media(id: {anime_id}) {{
        title {{
          english
          romaji
        }}
      }}
    }}
    '''
    data = fetch_anime_data(query_details)
    if data and 'data' in data and 'Media' in data['data']:
        english_title = data['data']['Media']['title'].get('english', None)
        romaji_title = data['data']['Media']['title'].get('romaji', '')
        add_favorite(user_id, romaji_title, english_title)
        await query.message.reply_text(f'Added "{english_title or romaji_title}" to your favorites.')
    else:
        await query.message.reply_text("Could not add to favorites. Details not found.")


async def remove_favorite_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    anime_id = query.data.split('_')[1]
    user_id = query.from_user.id

    # Fetch anime details to get the English title
    query_details = f'''
    {{
      Media(id: {anime_id}) {{
        title {{
          english
          romaji
        }}
      }}
    }}
    '''
    data = fetch_anime_data(query_details)
    if data and 'data' in data and 'Media' in data['data']:
        english_title = data['data']['Media']['title'].get('english', None)
        romaji_title = data['data']['Media']['title'].get('romaji', '')
        remove_favorite(user_id, romaji_title, english_title)
        await query.message.reply_text(f'Removed "{english_title or romaji_title}" from your favorites.')
    else:
        await query.message.reply_text("Could not remove from favorites. Details not found.")


async def show_favorites(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id if update.message else update.callback_query.from_user.id

    favorites = await get_favorites(user_id)
    
    if favorites:
        # Ensure no 'None' values in the list
        favorites = [title for title in favorites if title]
        if favorites:
            favorites_list = "\n".join(f"{i+1}. {title}" for i, title in enumerate(favorites))
            await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
                f"Here are your favorite animes:\n\n{favorites_list}")
        else:
            await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
                "You have no favorite anime.")
    else:
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            "You have no favorite anime.")


async def remove_favanime(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id if update.message else update.callback_query.from_user.id
    
    if not context.args:
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            "Please provide the indices of the anime you want to remove.")
        return

    try:
        indices = list(map(int, context.args[0].split(',')))
    except ValueError:
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            "Invalid input. Please provide a comma-separated list of indices.")
        return

    favorites = await get_favorites(user_id)
    
    if not favorites:
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            "You have no favorite anime.")
        return

    # Ensure indices are within the range of favorites
    indices = [index - 1 for index in indices if 1 <= index <= len(favorites)]

    if not indices:
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
            "No valid indices provided.")
        return

    removed_titles = []
    for index in indices:
        title = favorites[index]
        remove_favorite(user_id, title)
        removed_titles.append(title)

    await (update.message.reply_text if update.message else update.callback_query.message.reply_text)(
        f"Removed from favorites:\n" + "\n".join(removed_titles))

# Function to generate owner info message
async def owner_command(update: Update, context: CallbackContext) -> None:
    help_text = f"<b>○ Creator : <a href='tg://user?id=1196934318'>Ayan</a>\n○ Language : <code>Python 3</code>\n○ Anime Channel: <a href='https://t.me/newanimeshow'>New Anime Shows</a>\n○ Anime Group :<a href='https://t.me/newanimeshowsgroup'> New Anime Shows Group</a>\n○ Helper :<a href='tg://user?id=6965778216'> Helper</a>\n○ Source :<a href='tg://user?id=6965778216'> Click here</a></b>"
    await update.message.reply_text(help_text, parse_mode='HTML', disable_web_page_preview=True)

# Function to generate help message
async def help_command(update: Update, context: CallbackContext) -> None:
    help_text = """
    Welcome to Anime Bot Help!
    
    /start - Starts the bot.
    /weekly - Show weekly top anime.
    /trending - Show trending anime.
    /top - Show top anime list.
    /search - Search for an anime.
    /showfav - Show favorite anime.
    /removefavanime - Remove specific anime from favorites.
    /remind - Set a reminder for an anime.
    /showreminders - Show your reminders.
    /removereminder - Remove a reminder for an anime.
    /help - Show this help message.
    /owner - Show owners info.
    
    Enjoy using Anime Bot!
    """
    await update.message.reply_text(help_text)

async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    if not has_been_welcomed_today(user_id):
        # First-time welcome message with image from local PC
        image_path = 'animebot.jpg'  # Replace with the actual path to your image file
        caption = '''🌟 Welcome to AnimeBot! 🌟

Hello there! 👋 I'm AnimeBot, here to help you discover and explore the fascinating world of anime. Whether you're looking for the latest trending anime, top-rated shows, or simply want to search for something specific, I've got you covered!

🎉 To get started, simply type /start and let's embark on an anime adventure together!

📚 If you ever need assistance or want to learn more about what I can do, just type /help and I'll be here to guide you.

🎌 Let's dive into the exciting world of anime together! Enjoy exploring! 🎌
'''
        with open(image_path, 'rb') as photo:
            if update.message:
                await update.message.reply_photo(photo=photo, caption=caption)
            elif update.callback_query:
                await update.callback_query.message.reply_photo(photo=photo, caption=caption)

        # Update welcome status
        update_welcome_status(user_id)
    else:
        # Subsequent welcome message without image
        if update.message:
            await update.message.reply_text('''🌟 Ready to explore more anime? Choose an option: \n\n 📚 If you ever need assistance or want to learn more about what I can do, just type /help and I'll be here to guide you.''')
        elif update.callback_query:
            await update.callback_query.message.reply_text('''🌟 Ready to explore more anime? Choose an option: \n\n 📚 If you ever need assistance or want to learn more about what I can do, just type /help and I'll be here to guide you.''')

    # Your existing menu code
    keyboard = [
    [InlineKeyboardButton("Weekly Top Anime 📅", callback_data='weekly')],
    [InlineKeyboardButton("Trending Anime 📈", callback_data='trending')],
    [InlineKeyboardButton("Top Anime List 🏆", callback_data='top')],
    [InlineKeyboardButton("Search for Anime 🔍", callback_data='search')],
    [InlineKeyboardButton("Show Favorites ❤️", callback_data='showfav')]
]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text('🌟 Please choose an option to explore:', reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text('🌟 Please choose an option to explore:', reply_markup=reply_markup)


async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data in ['weekly', 'trending', 'top']:
        if query.data == 'weekly':
            await weekly(update, context)
        elif query.data == 'trending':
            await trending(update, context)
        elif query.data == 'top':
            await top(update, context)
    elif query.data == 'search':
        await search(update, context)
    elif query.data.startswith('detail_'):
        await details(update, context)
    elif query.data.startswith('addfav_'):
        await add_favorite_handler(update, context)
    elif query.data.startswith('removefav_'):
        await remove_favorite_handler(update, context)
    elif query.data == 'showfav':
        await show_favorites(update, context)
    elif query.data == 'start':
        await start(update, context)  # Call start with update and context

def set_bot_commands(token):
    url = f'https://api.telegram.org/bot{token}/setMyCommands'
    commands = [
        {'command': 'start', 'description': 'Start the bot'},
        {'command': 'weekly', 'description': 'Show weekly top anime'},
        {'command': 'trending', 'description': 'Show trending anime'},
        {'command': 'top', 'description': 'Show top anime list'},
        {'command': 'search', 'description': 'Search for an anime'},
        {'command': 'showfav', 'description': 'Show favorite anime list'},
        {'command': 'removefavanime', 'description': 'Remove specific anime from favorites'},
        {'command': 'remind', 'description': 'Set a reminder for an anime'},
        {'command': 'showreminders', 'description': 'Show all active reminders'},
        {'command': 'removereminder', 'description': 'Cancel a reminder for a specific anime'}
    ]
    response = requests.post(url, json={'commands': commands})
    print(response.json())  # For debugging


# Command handler to remove specific anime from favorites
async def remove_favorite_anime(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    args = context.args

    if not args:
        await update.message.reply_text('''Please enter the numbers corresponding to the anime you wish to remove, separated by commas. \n\n /removefavanime 1 ( 1,2,3 / 1, 2 , 3)''')
        return

    try:
        indices = list(map(int, re.split(r'[,\s]+', ' '.join(args))))
    except ValueError:
        await update.message.reply_text("Invalid numbers provided. Please enter valid numbers.")
        return

    # Get the current list of favorites
    favorites = await get_favorites(user_id)
    
    if not favorites:
        await update.message.reply_text("You have no favorite anime to remove.")
        return

    # Ensure the indices are within range
    if any(index < 1 or index > len(favorites) for index in indices):
        await update.message.reply_text(f"Some no. are out of range. \nPlease provide no. between 1 and {len(favorites)}.")
        return

    # Remove the selected favorites
    for index in sorted(indices, reverse=True):
        anime_name = favorites[index - 1]  # Convert 1-based index to 0-based index
        remove_favorite(user_id, anime_name)
    
    # Confirm removal and show updated list
    updated_favorites = await get_favorites(user_id)
    if updated_favorites:
        favorites_list = '\n'.join(f"{i+1}. {title}" for i, title in enumerate(updated_favorites))
        await update.message.reply_text(f"Updated favorite anime list:\n\n{favorites_list}")
    else:
        await update.message.reply_text("Your favorite anime list is now empty.")


def scheduler_job():
    # Run the asynchronous check_reminders function using asyncio.run
    asyncio.run(check_reminders())

async def main():
    # Initialize the application with the token
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('weekly', weekly))
    application.add_handler(CommandHandler('trending', trending))
    application.add_handler(CommandHandler('top', top))
    application.add_handler(CommandHandler('search', search))
    application.add_handler(CommandHandler('showfav', show_favorites))
    application.add_handler(CommandHandler('removefavanime', remove_favorite_anime))
    application.add_handler(CommandHandler('remind', remind_me))
    application.add_handler(CommandHandler('showreminders', show_reminders_command))
    application.add_handler(CommandHandler('removereminder', remove_reminder_command))
    application.add_handler(CommandHandler('help', help_command))  # Register /help command handler
    application.add_handler(CommandHandler('owner', owner_command))  # Register /owner command handler
    application.add_handler(CallbackQueryHandler(button, pattern='^start|weekly|trending|top|search|detail_|addfav_|removefav_|showfav'))

     # Initialize the database and scheduler
    init_db()
    init_welcome_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduler_job, IntervalTrigger(minutes=1))
    scheduler.start()

    # Start the Bot
    await application.start()
    await application.idle()

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Bot is running')

def run_http_server():
    port = int(os.getenv('PORT', 8000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    init_db()  # Initialize the database

    # Start the HTTP server in a separate thread
    threading.Thread(target=run_http_server).start()

    # Start the bot
    asyncio.run(main())
