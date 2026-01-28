import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import io
import os
from PIL import Image, ImageEnhance
from flask import Flask
from threading import Thread

# --- 1. CONFIGURATION ---
TOKEN = os.environ.get('DISCORD_TOKEN') 

# Channel where /success works
ALLOWED_CHANNEL_ID = 1465880033481720011

# Role required to use /announce (Admin/Staff Role)
ADMIN_ROLE_ID = 1465896921074897140

# Role to give NEW members automatically
NEW_MEMBER_ROLE_ID = 1465897609267777748

# --- 2. THE "HEARTBEAT" SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- 3. BOT SETUP ---
class VouchBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        # ENABLE MEMBER INTENT (Required for Auto-Role)
        intents.members = True 
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Commands synced globally.")

    async def on_ready(self):
        await self.change_presence(status=discord.Status.invisible)
        print(f'Logged in as {self.user} (Stealth Mode Active)')

bot = VouchBot()

# --- 4. COMMANDS ---

# COMMAND 1: /success (Open to everyone, locked to channel)
@bot.tree.command(name="success", description="Watermark and save your proof.")
@app_commands.describe(image="Upload your screenshot", note="Add a short side note (optional)")
async def success(interaction: discord.Interaction, image: discord.Attachment, note: str = None):
    
    # Channel Check
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Wrong channel! Please use <#{ALLOWED_CHANNEL_ID}>.", 
            ephemeral=True
        )
        return

    # File Type Check
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

        # Image Processing (Opacity 50%, Size 1/3)
        with Image.open(io.BytesIO(user_image_data)).convert("RGBA") as base_img:
            with Image.open(io.BytesIO(icon_data)).convert("RGBA") as watermark:
                
                target_width = max(base_img.width // 3, 100)
                aspect_ratio = watermark.height / watermark.width
                target_height = int(target_width * aspect_ratio)
                watermark = watermark.resize((target_width, target_height), Image.Resampling.LANCZOS)

                alpha = watermark.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(0.5)
                watermark.putalpha(alpha)

                watermark_layer = Image.new('RGBA', base_img.size, (0,0,0,0))
                for x in range(0, base_img.width, watermark.width):
                    for y in range(0, base_img.height, watermark.height):
                        watermark_layer.paste(watermark, (x, y))

                final_img = Image.alpha_composite(base_img, watermark_layer)

                output_buffer = io.BytesIO()
                final_img.save(output_buffer, format='PNG')
                output_buffer.seek(0)

                response_content = f"✅ **Vouch recorded by {interaction.user.mention}**"
                if note:
                    response_content += f"\n📝 **Note:** {note}"

                file = discord.File(fp=output_buffer, filename=f"vouched_{image.filename}")
                await interaction.followup.send(content=response_content, file=file)

    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send("❌ An error occurred processing the image.")

# COMMAND 2: /announce (Locked to specific Role ID)
# UPDATES: Added footer "Prime Refunds"
@bot.tree.command(name="announce", description="Post an official announcement.")
@app_commands.describe(
    title="The title of the announcement",
    message="Use \\n to create new lines (e.g. Line 1 \\n Line 2)",
    image="Optional: Upload a banner image for the bottom"
)
async def announce(interaction: discord.Interaction, title: str, message: str, image: discord.Attachment = None):
    
    # Check for the specific Admin Role ID
    user_role_ids = [role.id for role in interaction.user.roles]
    if ADMIN_ROLE_ID not in user_role_ids:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    # Process "newline" characters so you can type paragraphs
    formatted_message = message.replace('\\n', '\n')

    # Create Embed
    embed = discord.Embed(title=title, description=formatted_message, color=discord.Color(0xff7828))
    
    # Add Footer
    embed.set_footer(text="Prime Refunds")

    # If user provided an image, attach it as the big bottom banner
    if image:
        if image.content_type.startswith('image/'):
            embed.set_image(url=image.url)
    
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Sent!", ephemeral=True)

# --- 5. EVENTS ---

# Event: Auto-Role on Join
@bot.event
async def on_member_join(member):
    if NEW_MEMBER_ROLE_ID != 0:
        role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
                print(f"✅ Assigned role to {member.name}")
            except discord.Forbidden:
                print("❌ ERROR: Bot role is too low! Move the bot role HIGHER than the member role.")

# Event: Janitor & Traffic Cop
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
        
    if message.channel.id == ALLOWED_CHANNEL_ID:
        try:
            await message.delete()
            warning = await message.channel.send(f"{message.author.mention} ❌ This channel is for `/success` commands only.")
            await warning.delete(delay=5)
        except:
            pass 

    await bot.process_commands(message)

# --- 6. START ---
keep_alive()
bot.run(TOKEN)
