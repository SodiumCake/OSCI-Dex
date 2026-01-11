import os
import random
import re
import asyncio
from collections import deque
import time
from datetime import datetime
import aiohttp
import io
from interactions import (
    AutocompleteContext, Client, Intents, listen,
    SlashContext, slash_command,
    Embed, ActionRow, Button, ButtonStyle,
    ComponentContext, component_callback,
    Modal, ShortText, modal_callback, slash_option, OptionType,
    File,
)
from interactions.models.internal.localisation import LocalisedField
from objects import OBJECTS
import json

DATA_PATH = "data/collections.json"
CHANNELS_PATH = "data/channels.json"


# ===================== CLIENT =====================

client = Client(
    intents=Intents.DEFAULT | Intents.MESSAGE_CONTENT
)

# ===================== DATA =====================

CAPTIONS = [
    "hav an objec :3",
    "Selamat datang di objek OsciDex!",
    "Buset dapet apa tuh",
    "Selamat datang di oscidex dimana merdeka.",
    "Buset! dia dapet **LIMA**???",
    "kapan oosci 3b",
    "Thy End Is Now.",
    "Judgement.",
    "nggak punya ide caption <:Mrbones:1346744461711114240>",
    "nggak punya ide caption 2",
    "Look! an object!",
    "objek ini nggak pernah main roblok",
    "maret 17 2016",
]

def load_collections():
    if not os.path.exists(DATA_PATH):
        return {}

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_channels():
    if not os.path.exists(CHANNELS_PATH):
        return set()
    with open(CHANNELS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        return set(int(cid) for cid in data)


active_spawns = {}        # message_id -> data
auto_channels = load_channels()    # channel_id auto spawn
user_collections = load_collections()    # user_id -> list of caught objects
channel_activity = {}      # channel_id -> deque[timestamps]
spawn_cooldown = {}        # channel_id -> last_spawn_time


# ===================== UTIL =====================

def get_random_object():
    weights = [100 / o["rarity"] for o in OBJECTS]
    return random.choices(OBJECTS, weights=weights, k=1)[0]


def save_collections():
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(user_collections, f, indent=2)


def save_channels():
    os.makedirs(os.path.dirname(CHANNELS_PATH), exist_ok=True)
    with open(CHANNELS_PATH, "w", encoding="utf-8") as f:
        json.dump(list(auto_channels), f)


def add_to_collection(user_id: str, object_name: str):
    if user_id not in user_collections:
        user_collections[user_id] = []

    user_collections[user_id].append(object_name)
    save_collections()


def disabled_components():
    return [
        ActionRow(
            Button(
                style=ButtonStyle.SECONDARY,
                label="Catch me!",
                custom_id="expired_catch",
                disabled=True
            ),
            Button(
                style=ButtonStyle.SECONDARY,
                label="Rarity",
                custom_id="expired_rarity",
                disabled=True
            )
        )
    ]

def normalize_name(name: str):
    # Hilangkan spasi dan case-insensitive
    return name.replace(" ", "").lower()

def find_object_by_name(name: str):
    normalized = normalize_name(name)
    for obj in OBJECTS:
        if normalize_name(obj["name"]) == normalized:
            return obj
    return None




async def expire_spawn(message_id: int):
    await asyncio.sleep(120)  # 2 menit

    spawn = active_spawns.pop(str(message_id), None)
    if not spawn:
        return

    channel = client.get_channel(int(spawn["channel_id"]))
    if not channel:
        return

    try:
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(components=disabled_components())
    except:
        pass



# ===================== SPAWN =====================

async def spawn_object(channel, obj=None):
    if obj is None:
        obj = get_random_object()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(obj["image"], headers=headers) as resp:
            if resp.status != 200:
                print(f"FAILED to download image from {obj['image']}. Status: {resp.status}")
                return
            image_bytes = await resp.read()
            print(f"Downloaded {len(image_bytes)} bytes from {obj['image']}")

    if not image_bytes:
        print("Image bytes are empty!")
        return

    file = File(
        file=io.BytesIO(image_bytes),
        file_name="object.png"
    )


    components = [
        ActionRow(
            Button(
                style=ButtonStyle.PRIMARY,
                label="Catch me!",
                custom_id=f"catch_{obj['name']}"
            ),
            Button(
                style=ButtonStyle.SUCCESS,
                label="Rarity",
                custom_id=f"rarity_{obj['name']}"
            )
        )
    ]

    msg = await channel.send(
        content=random.choice(CAPTIONS),
        file=file,
        components=components
    )

    active_spawns[str(msg.id)] = {
        "object": obj,
        "channel_id": str(channel.id)
    }

    asyncio.create_task(expire_spawn(msg.id))


# ===================== AUTO SPAWN LOOP =====================

ACTIVITY_WINDOW = 60      # detik
ACTIVITY_THRESHOLD = 6   # minimal pesan
MIN_COOLDOWN = 120       # 2 menit
MAX_COOLDOWN = 240       # 4 menit

@listen()
async def on_message_create(event):
    msg = event.message
    if msg.author.bot:
        return

    channel_id = msg.channel.id
    now = time.time()

    # init deque
    if channel_id not in channel_activity:
        channel_activity[channel_id] = deque()

    activity = channel_activity[channel_id]
    activity.append(now)

    # bersihkan pesan lama
    while activity and now - activity[0] > ACTIVITY_WINDOW:
        activity.popleft()

    # tidak auto spawn jika channel tidak diaktifkan
    if channel_id not in auto_channels:
        return

    # sudah ada spawn aktif
    if any(v["channel_id"] == str(channel_id) for v in active_spawns.values()):
        return

    # belum cukup ramai
    if len(activity) < ACTIVITY_THRESHOLD:
        return

    # masih cooldown
    last = spawn_cooldown.get(channel_id, 0)
    if now - last < random.randint(MIN_COOLDOWN, MAX_COOLDOWN):
        return

    # SPAWN
    await spawn_object(msg.channel)
    spawn_cooldown[channel_id] = now


# ===================== SLASH COMMAND =====================

@slash_command(name="dex", description="OsciDex commands")
async def dex(ctx: SlashContext):
    pass

@dex.subcommand(
    sub_cmd_name="spawn",
    sub_cmd_description="Spawn objek (random atau tertentu)"
)
@slash_option(
    name="object",
    description="Nama objek yang ingin di-spawn",
    opt_type=OptionType.STRING,
    required=False,
    autocomplete=True
)
async def dex_spawn(ctx: SlashContext, object: str = None):
    if object:
        obj = find_object_by_name(object)
        if not obj:
            await ctx.send(
                f"Objek `{object}` tidak ditemukan.",
                ephemeral=True
            )
            return

        await spawn_object(ctx.channel, obj)
        await ctx.send(
            f"Objek **{obj['name']}** berhasil di-spawn.",
            ephemeral=True
        )
    else:
        await spawn_object(ctx.channel)
        await ctx.send(
            "Spawn random berhasil.",
            ephemeral=True
        )

@dex_spawn.autocomplete("object")
async def dex_spawn_autocomplete(ctx: AutocompleteContext):
    user_input = (ctx.input_text or "").lower()

    results = []
    for obj in OBJECTS:
        if user_input in obj["name"].lower():
            results.append({
                "name": obj["name"],
                "value": obj["name"]
            })

    await ctx.send(results[:25])


@dex.subcommand(sub_cmd_name="activate", sub_cmd_description="Auto spawn di channel ini")
async def dex_activate(ctx: SlashContext):
    auto_channels.add(ctx.channel.id)
    save_channels()
    await ctx.send("Auto spawn diaktifkan (1–4 menit).")

@dex.subcommand(sub_cmd_name="completions", sub_cmd_description="Lihat koleksi objek yang tersedia")
async def dex_collections(ctx: SlashContext):
    embed = Embed(
        title="OsciDex Completions",
        description="Daftar semua objek yang bisa kamu temukan!",
        color=0x00FF00
    )
    for obj in OBJECTS:
        embed.add_field(
            name=obj["name"],
            value=f"Rarity: **{obj['rarity']}**",
            inline=True
        )
    await ctx.send(embeds=embed)

@dex.subcommand(
    sub_cmd_name="collections",
    sub_cmd_description="Lihat progres koleksi OsciDex milikmu"
)
async def dex_completions(ctx: SlashContext):
    user_id = str(ctx.author.id)
    collection = user_collections.get(user_id, [])

    if not collection:
        await ctx.send(
            "Kamu belum punya objek apa pun :/\n-# skill issue :3"
        )
        return

    # hitung unique object
    unique_owned = set(collection)
    total_objects = len(OBJECTS)
    completion_percent = (len(unique_owned) / total_objects) * 100

    embed = Embed(
        title=f"OsciDex Completion — {ctx.author.username}",
        description=(
            f"Progress: **{len(unique_owned)}/{total_objects}** "
            f"({completion_percent:.1f}%)"
        ),
        color=0xFFD700
    )

    for name in sorted(unique_owned):
        count = collection.count(name)
        embed.add_field(
            name=name,
            value=f"Jumlah: **{count}x**",
            inline=True
        )

    await ctx.send(embeds=embed)

    

# ===================== BUTTONS =====================

@component_callback(re.compile(r"catch_.*"))
async def catch_button(ctx: ComponentContext):
    message_id = str(ctx.message.id)
    if message_id not in active_spawns:
        # Jika sudah expired, update pesan untuk mendisable button
        await ctx.edit_origin(components=disabled_components())
        await ctx.send("Objek sudah expired.", ephemeral=True)
        return

    modal = Modal(
        ShortText(
            label="Nama objek",
            custom_id="guess",
            placeholder="Ketik nama objek",
            required=True
        ),
        title="Catch the Object!",
        custom_id=f"catch:{ctx.message.id}"
    )
    await ctx.send_modal(modal)

@component_callback(re.compile(r"rarity_.*"))
async def rarity_button(ctx: ComponentContext):
    name = ctx.custom_id.split("_", 1)[1]
    obj = next(o for o in OBJECTS if o["name"] == name)
    await ctx.send(
        f"Rarity objek ini adalah **{obj['rarity']}**, Semakin kecil angkanya semakin langka objectnya",
        ephemeral=True
    )

# ===================== MODAL =====================

@modal_callback(re.compile(r"catch:\d+"))
async def on_modal(ctx, guess: str):
    message_id = ctx.custom_id.split(":", 1)[1]
    spawn = active_spawns.get(message_id)

    if not spawn:
        await ctx.send("Objek sudah expired.", ephemeral=True)
        return

    obj_name = spawn["object"]["name"]
    obj_color = spawn["object"]["color"]

    if normalize_name(guess) != normalize_name(obj_name):
        await ctx.send(
            f"<@{ctx.author.id}> salah bro. Kamu ngetik: `{guess}`"
        )
        return

    user_id = str(ctx.author.id)
    object_name = spawn["object"]["name"]

    add_to_collection(user_id, object_name)


    
    await ctx.send(
        f"<@{ctx.author.id}> kau menangkap **{obj_name}** `(#{obj_color}, +0%/+0%)`\n\n Ini adalah **objek baru** yang ditambahkan ke koleksimu!",
        ephemeral=False
    )

    active_spawns.pop(message_id, None)

# ===================== READY =====================

@listen()
async def on_ready():
    print(f"OsciDex online sebagai {client.user.tag}")
    
    # Debug print for auto spawn channels
    if auto_channels:
        debug_msg = "Loaded auto spawn in:\n"
        for channel_id in auto_channels:
            channel = client.get_channel(channel_id)
            if channel:
                server_name = channel.guild.name if channel.guild else "Unknown Server"
                channel_name = channel.name
                debug_msg += f"- {server_name}, {channel_name}\n"
            else:
                debug_msg += f"- Unknown Channel ({channel_id})\n"
        print(debug_msg.strip())
    else:
        print("No auto spawn channels loaded.")
# ===================== RUN =====================

client.start(os.environ["DISCORD_TOKEN"])


