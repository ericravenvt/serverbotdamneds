import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import datetime
from datetime import UTC
import logging
import a2s
import aiohttp
import time 
# Set up logging
logging.basicConfig(level=logging.INFO)

# Configuration
CONFIG = {
    'BOT_TOKEN': 'BOT_TOKEN',  # Discord bot token (get from Discord Developer Portal)
    'SERVER_IP': 'SERVER_IP',       # Game server IP (e.g., '148.113.199.214')
    'SERVER_PORT': 27015,                # Game server port (e.g., 27015)
    'SERVER_CHANNEL_ID': 1252566121073344564,              # Discord channel ID for status updates (e.g., 1252566121073344564)
    'STEAM_URL': 'steam://connect/SERVER_IP:PORT',  # Steam connect URL & or Discord Channel id (e.g., <#1318050934617538580>) you will need to remove ` from before and after {CONFIG['STEAM_URL']} however)
    'HIDE_PLAYER_NAMES': True,          # True: show "Player 1", False: show real names
    'FALLBACK_API_URL': None,             # Optional: URL for fallback API (e.g., 'http://localhost:3000/server')
    'SERVER_MESSAGE_ID': None,            # Optional: ID of the message to update (if you want to edit an existing message)
}

SERVER_MESSAGE_ID = None

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Button view for server status
class ServerButtonView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Join Server", style=discord.ButtonStyle.primary)
    async def join_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(f"Join the server: {CONFIG['STEAM_URL']}", ephemeral=True)

# Function to create the server status embed
def create_server_embed(server_data, status='Online'):
    embed = discord.Embed(
        title=server_data.get('name', 'Conan Exiles Server'),
        description=f"Join the server: {CONFIG['STEAM_URL']}",
        color=discord.Color.blue() if status == 'Online' else discord.Color.red(),
        timestamp=datetime.datetime.now(UTC)
    )
    embed.add_field(name='Status', value=status, inline=False)
    embed.add_field(name='Map', value=server_data.get('map', 'Unknown'), inline=True)
    embed.add_field(name='Players', value=f"{server_data.get('players', 0)}/{server_data.get('max_players', 0)}", inline=True)
    
    player_list = server_data.get('player_list', [])
    if CONFIG['HIDE_PLAYER_NAMES'] != "off" and player_list:
        now = int(time.time())
        # Prepare player text
        if CONFIG['HIDE_PLAYER_NAMES']:
            players = [f"Player {i+1} (Time: <t:{now - p['duration'] * 60}:t> <t:{now - p['duration'] * 60}:R>)" for i, p in enumerate(player_list)]
        else:
            players = [f"{p['name']} (Time: <t:{now - p['duration'] * 60}:t> <t:{now - p['duration'] * 60}:R>)" for p in player_list]
        
        # Split players into multiple fields to respect 1024-char limit per field
        current_field = []
        char_count = 0
        for player in players:
            player_len = len(player) + 1  # +1 for newline
            if char_count + player_len > 1024:
                embed.add_field(
                    name='Players Online',
                    value='\n'.join(current_field) or 'None',
                    inline=False
                )
                current_field = [player]
                char_count = player_len
            else:
                current_field.append(player)
                char_count += player_len
        
        # Add the last field if there are players left
        if current_field:
            embed.add_field(
                name='Players Online',
                value='\n'.join(current_field) or 'None',
                inline=False
            )
        
        # Check total embed size (rough estimate)
        total_chars = len(embed.title) + len(embed.description or '') + sum(len(f.name) + len(f.value) for f in embed.fields)
        if total_chars > 5500:  # Leave buffer below 6000
            embed.clear_fields()
            embed.add_field(name='Status', value=status, inline=False)
            embed.add_field(name='Map', value=server_data.get('map', 'Unknown'), inline=True)
            embed.add_field(name='Players', value=f"{server_data.get('players', 0)}/{server_data.get('max_players', 0)}", inline=True)
            embed.add_field(name='Players Online', value=f"{server_data.get('players', 0)} players (too many to list)", inline=False)
    
    elif CONFIG['HIDE_PLAYER_NAMES'] != "off":
        embed.add_field(name='Players Online', value=f"{server_data.get('players', 0)} players (names unavailable)", inline=False)

    # Set footer with clickable GitHub source link and timestamp
    embed.set_footer(text="Source: DJRLincs/ConanServerStatus")

    return embed

# Function to query the server
async def query_server():
    try:
        # Try A2S query
        server_address = (CONFIG['SERVER_IP'], CONFIG['SERVER_PORT'])
        server_info = await a2s.ainfo(server_address)
        players = await a2s.aplayers(server_address)
        logging.info("A2S query successful")
        return {
            'name': server_info.server_name or 'Conan Exiles Server',
            'map': server_info.map_name or 'Unknown',
            'players': server_info.player_count,
            'max_players': server_info.max_players,
            'player_list': [{'name': p.name or 'Unknown', 'duration': int(p.duration // 60)} for p in players]
        }
    except Exception as e:
        logging.error(f'A2S error: {e}')
        # Fallback to optional API if configured
        if CONFIG['FALLBACK_API_URL']:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(CONFIG['FALLBACK_API_URL']) as response:
                        js_data = await response.json()
                if js_data.get('status') == 'success':
                    logging.info("Fallback API query successful")
                    return js_data['data']
                else:
                    logging.error("Fallback API query failed")
                    raise Exception('Fallback API failed')
            except Exception as js_e:
                logging.error(f'Fallback API error: {js_e}')
        return None

# Task to update server status embed
@tasks.loop(minutes=5)
async def update_server_status():
    global SERVER_MESSAGE_ID
    try:
        channel = bot.get_channel(1252566121073344564)
        if not channel:
            logging.error(f"Server channel with ID {CONFIG['SERVER_CHANNEL_ID']} not found.")
            return

        server_data = await query_server()
        if server_data:
            embed = create_server_embed(server_data, status='Online')
        else:
            embed = create_server_embed(
                {'name': 'Conan Exiles Server', 'map': 'Unknown', 'players': 0, 'max_players': 0, 'player_list': []},
                status='Offline'
            )

        view = ServerButtonView()

        if SERVER_MESSAGE_ID:
            try:
                message = await channel.fetch_message(SERVER_MESSAGE_ID)
                await message.edit(embed=embed, view=view)
                logging.info("Updated server status embed.")
            except discord.errors.NotFound:
                logging.warning("Server status message not found, sending new one.")
                message = await channel.send(embed=embed, view=view)
                SERVER_MESSAGE_ID = message.id
                logging.info(f"Sent new server status message with ID {SERVER_MESSAGE_ID}.")
        else:
            message = await channel.send(embed=embed, view=view)
            SERVER_MESSAGE_ID = message.id
            logging.info(f"Sent initial server status message with ID {SERVER_MESSAGE_ID}.")

    except Exception as e:
        logging.error(f"Error in update_server_status: {e}")

@bot.event
async def on_ready():
    logging.info(f'Bot is ready as {bot.user}')
    
    # Start server status task
    if not update_server_status.is_running():
        logging.info("Starting server status update task...")
        update_server_status.start()

# Run the bot
if not CONFIG['BOT_TOKEN'] or CONFIG['BOT_TOKEN'] == 'YOUR_BOT_TOKEN_HERE':
    logging.error("BOT_TOKEN is not set. Please update CONFIG['BOT_TOKEN'] in the script.")
else:
    bot.run(CONFIG['BOT_TOKEN'])
