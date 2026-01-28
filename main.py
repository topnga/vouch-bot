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

# Role required to use /announce AND see Tickets (Admin)
ADMIN_ROLE_ID = 1465896921074897140

# The "Verified" Member Role (Given by RestoreCord)
MEMBER_ROLE_ID = 1465888391580090379

# The "Unverified" Role (Given on Join, Removed on Verify)
UNVERIFIED_ROLE_ID = 1465897609267777748

# Category ID where tickets will be created
TICKET_CATEGORY_ID = 1465924314854326313

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

# --- 3. TICKET SYSTEM CLASSES ---
class TicketLauncher(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.danger, emoji="📩", custom_id="ticket_button")
    async def ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        if TICKET_CATEGORY_ID == 0:
            await interaction.response.send_message("❌ Ticket Category ID not configured in code.", ephemeral=True)
            return

        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)
        
        if not category:
            await interaction.response.send_message("❌ Ticket Category not found.", ephemeral=True)
            return

        existing_channel = discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing_channel:
            await interaction.response.send_message(f"❌ You already have a ticket open: {existing_channel.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        admin_role = guild.get_role(ADMIN_ROLE_ID)
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                category=category,
                overwrites=overwrites
            )
            
            await interaction.response.send_message(f"✅ Ticket created: {channel.mention}", ephemeral=True)
            
            embed = discord.Embed(
                title=f"Support Ticket - {interaction.user.name}",
                description="Staff will be with you shortly.\nClick the button below to close this ticket.",
                color=discord.Color(0xff7828)
            )
            await channel.send(f"{interaction.user.mention}", embed=embed, view=CloseButton())

        except Exception as e:
            await interaction.response.send_message(f"❌ Error creating ticket: {e}", ephemeral=True)

class CloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 Ticket closing in 5 seconds...")
        await interaction.channel.delete()

# --- 4. BOT SETUP ---
class VouchBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True 
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketLauncher())
        self.add_view(CloseButton())
        await self.tree.sync()
        print("Commands synced globally.")

    async def on_ready(self):
        await self.change_presence(status=discord.Status.invisible)
        print(f'Logged in as {self.user} (Stealth Mode Active)')

bot = VouchBot()

# --- 5. COMMANDS ---

# COMMAND 1: /success
@bot.tree.command(name="success", description="Watermark and save your proof.")
@app_commands.describe(image="Upload your screenshot", note="Add a short side note (optional)")
async def success(interaction: discord.Interaction, image: discord.Attachment, note: str = None):
    if interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message(f"❌ Wrong channel! Please use <#{ALLOWED_CHANNEL_ID}>.", ephemeral=True)
        return
    if not image.content_type or not image.content_type.startswith('image/'):
        await interaction.response.send_message("❌ Invalid file type. Please upload an image.", ephemeral=True)
        return

    await interaction.response.defer()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image.url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to download image.")
                    return
                user_image_data = await resp.read()
            if not interaction.guild.icon:
                await interaction.followup.send("❌ This server has no icon.")
                return
            icon_url = interaction.guild.icon.replace(format='png', size=128).url
            async with session.get(icon_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to retrieve server icon.")
                    return
                icon_data = await resp.read()

        with Image.open(io.BytesIO(user_image_data)).convert("RGBA") as base_img:
            with Image.open(io.BytesIO(icon_data)).convert("RGBA") as watermark:
                target_width = max(base_img.width // 3, 100)
                aspect_ratio = watermark.height / watermark.width
                target_height = int(target_width * aspect_ratio)
                watermark = watermark.resize((target_width, target_height), Image.Resampling.LANCZOS)
                
                # UPDATED HERE: 0.25 Opacity (25%)
                alpha = watermark.split()[3]
                alpha = ImageEnhance.Brightness(alpha).enhance(0.25)
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

# COMMAND 2: /announce
@bot.tree.command(name="announce", description="Post an official announcement.")
@app_commands.describe(title="The title", message="Use \\n for new lines", image="Optional banner image")
async def announce(interaction: discord.Interaction, title: str, message: str, image: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True)

    user_role_ids = [role.id for role in interaction.user.roles]
    if ADMIN_ROLE_ID not in user_role_ids:
        await interaction.followup.send("❌ You do not have permission to use this command.")
        return

    try:
        formatted_message = message.replace('\\n', '\n')
        
        if len(formatted_message) > 4096:
            await interaction.followup.send("❌ Error: Message too long (Max 4096 chars).")
            return

        embed = discord.Embed(title=title, description=formatted_message, color=discord.Color(0xff7828))
        embed.set_footer(text="Prime Refunds")
        
        if image:
            if image.content_type.startswith('image/'):
                embed.set_image(url=image.url)
            else:
                await interaction.followup.send("⚠️ Warning: Attachment was not an image.")

        await interaction.channel.send(embed=embed)
        await interaction.followup.send("✅ Sent!")

    except discord.Forbidden:
        await interaction.followup.send("❌ Permission Error: I can't send messages here. Check Channel Permissions.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

# COMMAND 3: /ticketpanel
@bot.tree.command(name="ticketpanel", description="Setup the support ticket panel.")
async def ticketpanel(interaction: discord.Interaction, title: str = "Support Tickets", description: str = "Click below to open a ticket."):
    user_role_ids = [role.id for role in interaction.user.roles]
    if ADMIN_ROLE_ID not in user_role_ids:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    embed = discord.Embed(title=title, description=description, color=discord.Color(0xff7828))
    embed.set_footer(text="Prime Refunds Support")
    
    await interaction.channel.send(embed=embed, view=TicketLauncher())
    await interaction.response.send_message("✅ Ticket panel created!", ephemeral=True)

# --- 6. EVENTS & ROLE LOGIC ---

@bot.event
async def on_member_join(member):
    if UNVERIFIED_ROLE_ID != 0:
        role = member.guild.get_role(UNVERIFIED_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
                print(f"✅ Assigned Unverified role to {member.name}")
            except discord.Forbidden:
                print("❌ ERROR: Bot role is too low to assign Unverified role!")

@bot.event
async def on_member_update(before, after):
    member_role = after.guild.get_role(MEMBER_ROLE_ID)
    unverified_role = after.guild.get_role(UNVERIFIED_ROLE_ID)
    
    if member_role in after.roles and unverified_role in after.roles:
        try:
            await after.remove_roles(unverified_role)
            print(f"🔄 Verified: Removed Unverified role from {after.name}")
        except discord.Forbidden:
            print("❌ ERROR: Bot role is too low to remove Unverified role!")

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

# --- 7. START ---
keep_alive()
bot.run(TOKEN)
