import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import io
import os
from PIL import Image, ImageEnhance
from flask import Flask
from threading import Thread

# --- CONFIGURATION ---
TOKEN = os.environ.get('DISCORD_TOKEN') 

# 1. CHANNEL ID (Replace with your actual Channel ID)
ALLOWED_CHANNEL_ID = 1465880033481720011

# 2. ROLE ID (Security)
# If you want to restrict this command to a specific role (e.g., "Client"), 
# paste the Role ID below. If you put 0, EVERYONE can use it.
ALLOWED_ROLE_ID = 1465888391580090379  

# --- THE "HEARTBEAT" SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT SETUP ---
class VouchBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Commands synced globally.")

    async def on_ready(self):
        await self.change_presence(status=discord.Status.invisible)
        print(f'Logged in as {self.user} (Stealth Mode Active)')

bot = VouchBot()

# --- COMMANDS ---

# Updated command name to "/success" and added "note" field
@bot.tree.command(name="success", description="Watermark and save your proof.")
@app_commands.describe(image="Upload your screenshot", note="Add a short side note (optional)")
async def success(interaction: discord.Interaction, image: discord.Attachment, note: str = None):
    
    # --- 1. CHANNEL CHECK ---
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Wrong channel! Please use <#{ALLOWED_CHANNEL_ID}>.", 
            ephemeral=True
        )
        return

    # --- 2. ROLE CHECK (New Feature) ---
    # Only checks if you set a Role ID above.
    if ALLOWED_ROLE_ID != 0:
        # Get list of user's role IDs
        user_role_ids = [role.id for role in interaction.user.roles]
        if ALLOWED_ROLE_ID not in user_role_ids:
            await interaction.response.send_message(
                f"❌ You need the <@&{ALLOWED_ROLE_ID}> role to use this command.", 
                ephemeral=True
            )
            return

    # --- FILE CHECK ---
    if not image.content_type or not image.content_type.startswith('image/'):
        await interaction.response.send_message("❌ Invalid file type. Please upload an image.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        async with aiohttp.ClientSession() as session:
            # Download User Image
            async with session.get(image.url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to download image.")
                    return
                user_image_data = await resp.read()

            # Download Server Icon
            if not interaction.guild.icon:
                await interaction.followup.send("❌ This server has no icon.")
                return
            
            icon_url = interaction.guild.icon.replace(format='png', size=128).url
            async with session.get(icon_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to retrieve server icon.")
                    return
                icon_data = await resp.read()

        # --- IMAGE PROCESSING ---
        with Image.open(io.BytesIO(user_image_data)).convert("RGBA") as base_img:
            with Image.open(io.BytesIO(icon_data)).convert("RGBA") as watermark:
                
                # UPDATE: Increased size (width // 3 instead of 6)
                target_width = max(base_img.width // 3, 100)
                aspect_ratio = watermark.height / watermark.width
                target_height = int(target_width * aspect_ratio)
                watermark = watermark.resize((target_width, target_height), Image.Resampling.LANCZOS)

                # UPDATE: Increased Opacity to 50% (0.5)
                alpha = watermark.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(0.5)
                watermark.putalpha(alpha)

                # Tile the watermark
                watermark_layer = Image.new('RGBA', base_img.size, (0,0,0,0))
                for x in range(0, base_img.width, watermark.width):
                    for y in range(0, base_img.height, watermark.height):
                        watermark_layer.paste(watermark, (x, y))

                final_img = Image.alpha_composite(base_img, watermark_layer)

                # Save result
                output_buffer = io.BytesIO()
                final_img.save(output_buffer, format='PNG')
                output_buffer.seek(0)

                # Prepare the final message
                response_content = f"✅ **Vouch recorded by {interaction.user.mention}**"
                if note:
                    response_content += f"\n📝 **Note:** {note}"

                file = discord.File(fp=output_buffer, filename=f"vouched_{image.filename}")
                await interaction.followup.send(content=response_content, file=file)

    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send("❌ An error occurred processing the image.")

@bot.tree.command(name="announce", description="Post an official announcement.")
@app_commands.checks.has_permissions(administrator=True)
async def announce(interaction: discord.Interaction, title: str, message: str):
    embed = discord.Embed(title=title, description=message, color=discord.Color.gold())
    embed.set_footer(text=f"Announcement by {interaction.user.display_name}")
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Sent!", ephemeral=True)

# --- JANITOR & TRAFFIC COP ---
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
        
    if message.channel.id == ALLOWED_CHANNEL_ID:
        try:
            await message.delete()
            # Updated to mention /success
            warning = await message.channel.send(f"{message.author.mention} ❌ This channel is for `/success` commands only.")
            await warning.delete(delay=5)
        except:
            pass 

    await bot.process_commands(message)

# --- START SERVER & BOT ---
keep_alive()
bot.run(TOKEN)
