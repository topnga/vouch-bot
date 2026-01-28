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
# We get the token securely from Render's Environment Variables later
TOKEN = os.environ.get('DISCORD_TOKEN') 

# REPLACE THIS with your actual Vouch Channel ID (Right-click channel -> Copy ID)
ALLOWED_CHANNEL_ID = 1465880033481720011

# --- THE "HEARTBEAT" SERVER (For UptimeRobot) ---
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
        # Intents allow the bot to read messages (needed for the Janitor system)
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Commands synced globally.")

    async def on_ready(self):
        # Stealth Mode: Sets bot to invisible
        await self.change_presence(status=discord.Status.invisible)
        print(f'Logged in as {self.user} (Stealth Mode Active)')

bot = VouchBot()

# --- COMMANDS ---

@bot.tree.command(name="vouch", description="Watermark and save your proof.")
@app_commands.describe(image="Upload your screenshot here")
async def vouch(interaction: discord.Interaction, image: discord.Attachment):
    # --- CHANNEL LOCK ---
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Wrong channel! Please use <#{ALLOWED_CHANNEL_ID}>.", 
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
                
                # Resize watermark relative to image size
                target_width = max(base_img.width // 6, 50)
                aspect_ratio = watermark.height / watermark.width
                target_height = int(target_width * aspect_ratio)
                watermark = watermark.resize((target_width, target_height), Image.Resampling.LANCZOS)

                # Set Opacity to 20%
                alpha = watermark.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(0.2)
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

                file = discord.File(fp=output_buffer, filename=f"vouched_{image.filename}")
                await interaction.followup.send(content=f"✅ **Vouch recorded by {interaction.user.mention}**", file=file)

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
        
    # Only run Janitor inside the Vouch Channel
    if message.channel.id == ALLOWED_CHANNEL_ID:
        try:
            # Delete any message that is just text (not a bot command interaction)
            await message.delete()
            warning = await message.channel.send(f"{message.author.mention} ❌ This channel is for `/vouch` commands only.")
            # Auto-delete warning after 5 seconds
            await warning.delete(delay=5)
        except:
            pass # Permissions error or message already deleted

    await bot.process_commands(message)

# --- START SERVER & BOT ---
keep_alive()

bot.run(TOKEN)
