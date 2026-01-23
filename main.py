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
    File, Permissions, StringSelectMenu, StringSelectOption
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
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def load_channels():
    if not os.path.exists(CHANNELS_PATH):
        return set()
    with open(CHANNELS_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return set()
        data = json.loads(content)
        return set(int(cid) for cid in data)


active_spawns = {}        # message_id -> data
auto_channels = load_channels()    # channel_id auto spawn
user_collections = load_collections()    # user_id -> list dari objek yang tertangkap user
channel_activity = {}      # channel_id -> deque[timestamps]
spawn_cooldown = {}        # channel_id -> last_spawn_time


# ===================== UTIL =====================

def get_random_object():
    # Rarity kecil (seperti Sodium=1) sekarang benar-benar langka karena bobotnya paling kecil
    weights = [o["rarity"] for o in OBJECTS]
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
    # Tunggu 5 menit (300 detik) SEBELUM mengecek apakah spawn masih aktif
    await asyncio.sleep(300)  # 5 menit

    # Cek apakah spawn masih ada di active_spawns (berarti belum ditangkap)
    # Gunakan .get() agar tidak menghapusnya dulu, kita hanya hapus jika benar-benar expired
    spawn = active_spawns.get(str(message_id))
    if not spawn:
        return

    # Hapus dari active_spawns karena sudah expired
    active_spawns.pop(str(message_id), None)

    channel = client.get_channel(int(spawn["channel_id"]))
    if not channel:
        return

    try:
        msg = await channel.fetch_message(int(message_id))
        # Cek apakah pesan masih punya komponen sebelum diedit
        if msg.components:
            await msg.edit(components=disabled_components())
    except:
        pass



# ===================== SPAWN =====================

async def spawn_object(channel, obj=None, forced_shiny=None):
    if obj is None:
        obj = get_random_object()

    # tentukan status shiny: wajib jika ditentukan, jika tidak, acak 1%
    is_shiny = forced_shiny if forced_shiny is not None else (random.random() < 0.01)

    # Memakai aiohttp untuk download gambar
    ext = "gif" if obj["image"].lower().endswith((".gif", ".gifv")) else "png"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    image_bytes = None
    try:
        async with aiohttp.ClientSession() as session:
            # Imgur gifv diconvert menjadi gif untuk attachment
            img_url = obj["image"].replace(".gifv", ".gif")
            async with session.get(img_url, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    print(f"FAILED to download image from {img_url}. Status: {resp.status}")
                    return
                image_bytes = await resp.read()
    except Exception as e:
        print(f"Error downloading image: {e}")
        return

    if not image_bytes:
        return

    file = File(
        file=io.BytesIO(image_bytes),
        file_name=f"object.{ext}"
    )

    msg = await channel.send(
        content=random.choice(CAPTIONS) + (" ✨" if is_shiny else ""),
        files=[file],
        components=[
            ActionRow(
                Button(
                    style=ButtonStyle.PRIMARY,
                    label="Catch me!",
                    custom_id="catch_btn"
                ),
                Button(
                    style=ButtonStyle.SUCCESS,
                    label="Rarity",
                    custom_id="rarity_btn"
                )
            )
        ]
    )

    active_spawns[str(msg.id)] = {
        "object": obj,
        "channel_id": str(channel.id),
        "is_shiny": is_shiny
    }

    asyncio.create_task(expire_spawn(msg.id))


# ===================== AUTO SPAWN LOOP =====================

ACTIVITY_WINDOW = 60      # detik
ACTIVITY_THRESHOLD = 6   # minimal pesan
MIN_COOLDOWN = 5       
MAX_COOLDOWN = 30       

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

    # bersihkan pesan lama di semua channel
    for activity in channel_activity.values():
        while activity and now - activity[0] > ACTIVITY_WINDOW:
            activity.popleft()

    # Hitung total aktivitas HANYA untuk server (guild) saat ini
    current_guild = msg.guild
    server_activity = 0
    if current_guild:
        for channel in current_guild.channels:
            if channel.id in channel_activity:
                server_activity += len(channel_activity[channel.id])

    # tidak auto spawn jika channel tidak diaktifkan
    if channel_id not in auto_channels:
        # tapi jika server ramai secara keseluruhan, coba spawn di channel yang aktif DI SERVER INI
        if server_activity >= ACTIVITY_THRESHOLD * 2: 
            # Cari channel aktif DI SERVER INI yang tidak sedang dalam cooldown
            for active_id in auto_channels:
                target_channel = client.get_channel(active_id)
                if target_channel and target_channel.guild and target_channel.guild.id == current_guild.id:
                    if not any(v["channel_id"] == str(active_id) for v in active_spawns.values()):
                        last_active = spawn_cooldown.get(active_id, 0)
                        if now - last_active >= random.randint(MIN_COOLDOWN, MAX_COOLDOWN):
                            await spawn_object(target_channel)
                            spawn_cooldown[active_id] = now
                            return
        return

    # sudah ada spawn aktif
    if any(v["channel_id"] == str(channel_id) for v in active_spawns.values()):
        return

    # belum cukup ramai (cek aktivitas channel lokal ATAU server secara keseluruhan)
    if len(activity) < ACTIVITY_THRESHOLD and server_activity < ACTIVITY_THRESHOLD * 1.5:
        return

    # masih cooldown
    last = spawn_cooldown.get(channel_id, 0)
    if now - last < random.randint(MIN_COOLDOWN, MAX_COOLDOWN):
        return

    # SPAWN
    await spawn_object(msg.channel)
    spawn_cooldown[channel_id] = now
    # Hapus pesan yang men-trigger spawn untuk mencegah "Interaction already acknowledged" jika user cepat klik
    try:
        if msg.id:
            pass # Kita tidak hapus pesan user, tapi kita pastikan modal dikirim dengan benar
    except:
        pass


# ===================== SLASH COMMAND =====================

@slash_command(name="dex", description="OsciDex commands")
async def dex(ctx: SlashContext):
    pass

@dex.subcommand(
    sub_cmd_name="guide",
    sub_cmd_description="Rules dan Cara main Oscidex!"
)
async def info_command(ctx: SlashContext):
    embed = Embed(
        title="📖 OsciDex Guide",
        description=(
            "Selamat datang di **OsciDex**! Bot koleksi objek interaktif.\n\n"
            "**Cara Bermain:**\n"
            "1. **Tunggu Objek Muncul**: Objek akan muncul secara otomatis di channel yang aktif jika ada percakapan ramai.\n"
            "2. **Tangkap Objek**: Klik tombol **Catch me!** dan ketikkan nama objek yang muncul di gambar.\n"
            "3. **Koleksi**: Cek koleksimu dengan `/dex collections`.\n\n"
            "**Tips:**\n"
            "• Objek memiliki tingkat **Rarity** (angka lebih kecil = lebih langka).\n"
            "• Ada peluang **1%** mendapatkan versi **Shiny ✨** yang langka!\n"
            "• Objek akan expired dalam **5 menit** jika tidak ditangkap."
        ),
        color=0x5865F2,
        url="http://github.com/SodiumCake/OSCI-Dex"
    )
    await ctx.send(
        embeds=embed,
        components=[
            ActionRow(
                Button(
                    style=ButtonStyle.URL,
                    label=":3",
                    url="https://example.com"
                )
            )
        ]
    )

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
@slash_option(
    name="shiny",
    description="Paksa objek menjadi shiny?",
    opt_type=OptionType.BOOLEAN,
    required=False
)
async def dex_spawn(ctx: SlashContext, object: str = None, shiny: bool = None):
    # ================= ADMIN CHECK =================
    if not ctx.author.has_permission(Permissions.ADMINISTRATOR):
        await ctx.send("Mau ngapain hayoo <:sololololo:1366327726553698304>")
        return

    # Defer interaction untuk menghindari timeout
    await ctx.defer(ephemeral=True)

    if object:
        obj = find_object_by_name(object)
        if not obj:
            await ctx.send(
                f"Objek `{object}` tidak ditemukan.",
                ephemeral=True
            )
            return

        await spawn_object(ctx.channel, obj, forced_shiny=shiny)
        await ctx.send(
            f"Objek **{obj['name']}**{' (Shiny ✨)' if shiny else ''} berhasil di-spawn.",
            ephemeral=True
        )
    else:
        await spawn_object(ctx.channel, forced_shiny=shiny)
        await ctx.send(
            f"Spawn random{' (Shiny ✨)' if shiny else ''} berhasil.",
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

    # pakai try-except untuk jaga jaga error autocomplete
    try:
        await ctx.send(results[:25])
    except:
        pass


@dex.subcommand(
    sub_cmd_name="trade",
    sub_cmd_description="Trade objek dengan user lain"
)
@slash_option(
    name="user",
    description="User yang ingin diajak trade",
    opt_type=OptionType.USER,
    required=True
)
@slash_option(
    name="your_object",
    description="Objek milikmu yang ingin ditukar",
    opt_type=OptionType.STRING,
    required=True,
    autocomplete=True
)
@slash_option(
    name="their_object",
    description="Objek milik mereka yang kamu inginkan (Kosongkan jika hanya ingin memberi)",
    opt_type=OptionType.STRING,
    required=False,
    autocomplete=True
)
async def dex_trade(ctx: SlashContext, user, your_object: str, their_object: str = None):
    if user.id == ctx.author.id:
        await ctx.send("Kamu tidak bisa trade dengan diri sendiri🥶")
        return

    sender_id = str(ctx.author.id)
    receiver_id = str(user.id)
    
    sender_coll = user_collections.get(sender_id, [])
    receiver_coll = user_collections.get(receiver_id, [])

    if your_object not in sender_coll:
        await ctx.send(f"Kamu tidak memiliki **{your_object}**.")
        return
    
    if their_object and their_object not in receiver_coll:
        await ctx.send(f"<@{receiver_id}> tidak memiliki **{their_object}**.")
        return

    offer_text = f"**Memberi:** {your_object}\n"
    if their_object:
        offer_text += f"**Menerima:** {their_object}\n\n"
        title = "Trade Offer"
    else:
        offer_text += "**Menerima:** - (Gift/Pemberian)\n\n"
        title = "Trade Offer"

    embed = Embed(
        title=title,
        description=(
            f"<@{sender_id}> ingin mengajak trade!\n\n"
            f"{offer_text}"
            f"Apakah <@{receiver_id}> setuju?"
        ),
        color=0xFFD700
    )

    components = [
        ActionRow(
            Button(
                style=ButtonStyle.SUCCESS,
                label="Accept",
                custom_id=f"trade_accept_{sender_id}_{receiver_id}_{your_object}_{their_object if their_object else 'NONE'}"
            ),
            Button(
                style=ButtonStyle.DANGER,
                label="Decline",
                custom_id=f"trade_decline_{sender_id}_{receiver_id}"
            )
        )
    ]

    await ctx.send(content=f"<@{receiver_id}>", embeds=embed, components=components)

@component_callback(re.compile(r"trade_accept_(\d+)_(\d+)_(.+?)_(.+)"))
async def trade_accept_callback(ctx: ComponentContext):
    parts = ctx.custom_id.split("_")
    sender_id = parts[2]
    receiver_id = parts[3]
    sender_obj = parts[4]
    receiver_obj = parts[5] if parts[5] != "NONE" else None

    if str(ctx.author.id) != receiver_id:
        await ctx.send("Hanya penerima trade yang bisa memproses ini.", ephemeral=True)
        return

    # Re-verify coleksi (menjegah race condition)
    sender_coll = user_collections.get(sender_id, [])
    receiver_coll = user_collections.get(receiver_id, [])

    if sender_obj not in sender_coll:
        await ctx.edit_origin(content=f"Trade gagal karena <@{sender_id}> tidak lagi memiliki **{sender_obj}**.", embeds=[], components=[])
        return
        
    if receiver_obj and receiver_obj not in receiver_coll:
        await ctx.edit_origin(content=f"Trade gagal karena <@{receiver_id}> tidak lagi memiliki **{receiver_obj}**.", embeds=[], components=[])
        return

    # Memproses trade
    user_collections[sender_id].remove(sender_obj)
    if receiver_obj:
        user_collections[sender_id].append(receiver_obj)
        user_collections[receiver_id].remove(receiver_obj)
    
    user_collections[receiver_id].append(sender_obj)
    
    save_collections()

    if receiver_obj:
        msg = f"Trade Sukses!\n<@{sender_id}> menerima **{receiver_obj}**\n<@{receiver_id}> menerima **{sender_obj}**"
    else:
        msg = f"Trade Sukses!\n<@{receiver_id}> menerima **{sender_obj}** dari <@{sender_id}>"

    await ctx.edit_origin(
        content=msg,
        embeds=[],
        components=[]
    )

@component_callback(re.compile(r"trade_decline_(\d+)_(\d+)"))
async def trade_decline_callback(ctx: ComponentContext):
    parts = ctx.custom_id.split("_")
    receiver_id = parts[3]

    if str(ctx.author.id) != receiver_id:
        await ctx.send("Hanya penerima trade yang bisa memproses ini.", ephemeral=True)
        return

    await ctx.edit_origin(content="Trade ditolak.", embeds=[], components=[])

@dex_trade.autocomplete("your_object")
@dex_trade.autocomplete("their_object")
async def trade_autocomplete(ctx: AutocompleteContext):
    user_input = (ctx.input_text or "").lower()
    # menampilkan semua objek yang dimiliki uswr
    results = []
    # combinasi objek normal dan shiny
    for obj in OBJECTS:
        names = [obj["name"], f"{obj['name']} ✨"]
        for n in names:
            if user_input in n.lower():
                results.append({"name": n, "value": n})
    
    try:
        await ctx.send(results[:25])
    except:
        pass


@dex.subcommand(
    sub_cmd_name="wave",
    sub_cmd_description="Spawn 3 objek sekaligus (Owner Only)"
)
async def dex_wave(ctx: SlashContext):
    # Sodiums
    if str(ctx.author.id) != "985457908961660960":
        await ctx.send("Anak nakal <:indo_geram:1462270643436388463>")
        return
    await ctx.defer(ephemeral=True)

    # Spawn 3 random objects
    for i in range(3):
        await spawn_object(ctx.channel)
        # delay agar nggak di rate limit
        await asyncio.sleep(0.5)

    await ctx.send("Wavey wavey")


@dex.subcommand(
    sub_cmd_name="edit",
    sub_cmd_description="Edit koleksi user (ADMIN ONLY)"
)
@slash_option(
    name="action",
    description="Tambah atau hapus objek dari koleksi user",
    opt_type=OptionType.STRING,
    required=True,
    choices=[
        {"name": "add", "value": "add"},
        {"name": "remove", "value": "remove"},
        {"name": "shinify", "value": "shinify"},
        {"name": "unshinify", "value": "unshinify"},
    ]
)
@slash_option(
    name="target_user",
    description="User yang ingin diedit koleksinya",
    opt_type=OptionType.USER,
    required=True
)
@slash_option(
    name="object",
    description="Nama objek",
    opt_type=OptionType.STRING,
    required=True,
    autocomplete=True
)
async def dex_edit(
    ctx: SlashContext,
    action: str,
    target_user: str,
    object: str,
):
    # ================= ADMIN CHECK =================
    if not ctx.author.has_permission(Permissions.ADMINISTRATOR):
        await ctx.send("Mau ngapain hayoo <:sololololo:1366327726553698304>")
        return

    # target_user akan berupa objek Member/User jika OptionType.USER digunakan.
    uid = str(target_user.id) if hasattr(target_user, "id") else str(target_user)
    action = action.lower()
    obj = find_object_by_name(object)

    if not obj:
        await ctx.send(f"Objek `{object}` tidak ditemukan di database global.", ephemeral=True)
        return

    if uid not in user_collections:
        user_collections[uid] = []

    # ================= ADD =================
    if action == "add":
        user_collections[uid].append(obj["name"])
        save_collections()
        await ctx.send(
            f"Berhasil menambahkan **{obj['name']}** ke koleksi <@{uid}> nya :3c",
        )

    # ================= REMOVE =================
    elif action == "remove":
        if obj["name"] not in user_collections[uid]:
            await ctx.send(
                f"<@{uid}> tidak memiliki **{obj['name']}** di koleksinya.",
                ephemeral=True
            )
            return

        user_collections[uid].remove(obj["name"])
        save_collections()

        await ctx.send(
            f"Berhasil menghapus **{obj['name']}** dari koleksi <@{uid}> <:yey:1345311537660825702> <:yey:1345311537660825702> <:yey:1345311537660825702>",
        )

    # ================= SHINIFY =================
    elif action == "shinify":
        if obj["name"] not in user_collections[uid]:
            await ctx.send(f"<@{uid}> tidak memiliki versi biasa dari **{obj['name']}**.", ephemeral=True)
            return
        
        shiny_name = f"{obj['name']} ✨"
        user_collections[uid].remove(obj["name"])
        user_collections[uid].append(shiny_name)
        save_collections()
        await ctx.send(f"Berhasil mengubah **{obj['name']}** milik <@{uid}> menjadi **Shiny** ✨!")

    # ================= UNSHINIFY =================
    elif action == "unshinify":
        shiny_name = f"{obj['name']} ✨"
        if shiny_name not in user_collections[uid]:
            await ctx.send(f"<@{uid}> tidak memiliki versi **Shiny** dari **{obj['name']}**.", ephemeral=True)
            return
        
        user_collections[uid].remove(shiny_name)
        user_collections[uid].append(obj["name"])
        save_collections()
        await ctx.send(f"Berhasil mengubah **{obj['name']} ✨** milik <@{uid}> kembali menjadi versi biasa.")


@dex_edit.autocomplete("object")
async def dex_edit_autocomplete(ctx: AutocompleteContext):
    user_input = (ctx.input_text or "").lower()
    results = []
    for obj in OBJECTS:
        if user_input in obj["name"].lower():
            results.append({"name": obj["name"], "value": obj["name"]})
    try:
        await ctx.send(results[:25])
    except:
        pass


@dex.subcommand(sub_cmd_name="activate", sub_cmd_description="Auto spawn di channel ini")
async def dex_activate(ctx: SlashContext):
    await ctx.defer()
    auto_channels.add(ctx.channel.id)
    save_channels()
    await ctx.send("Auto spawn diaktifkan (1–4 menit).")

@dex.subcommand(sub_cmd_name="completions", sub_cmd_description="Lihat koleksi objek yang tersedia")
async def dex_collections(ctx: SlashContext):
    await send_paginated_embed(ctx, OBJECTS, "OsciDex Completions", "Daftar semua objek yang bisa kamu temukan!")

@dex.subcommand(
    sub_cmd_name="list",
    sub_cmd_description="Lihat koleksi objekmu dan tampilkan card"
)
@slash_option(
    name="object",
    description="Langsung tampilkan card untuk objek tertentu",
    opt_type=OptionType.STRING,
    required=False,
    autocomplete=True
)
async def dex_list(ctx: SlashContext, object: str = None):
    user_id = str(ctx.author.id)
    collection = user_collections.get(user_id, [])

    if not collection:
        await ctx.send("Koleksimu masih kosong! Ayo tangkap objek yang muncul di channel. <:indo_cute:1366327726553698304>")
        return

    # Jika parameter object diisi, langsung tampilkan card
    if object:
        if object not in collection:
            await ctx.send(f"Kamu tidak memiliki **{object}** di koleksimu.", ephemeral=True)
            return
            
        clean_name = object.replace(" ✨", "")
        obj_data = find_object_by_name(clean_name)
        card_url = obj_data.get("card") or obj_data.get("image") if obj_data else None
        
        if not obj_data or not card_url:
            await ctx.send(f"Objek **{object}** ini belum punya card.")
            return

        await ctx.defer()
        img_url = card_url
        file_ext = "gif" if img_url.lower().endswith(".gif") or ".gifv" in img_url.lower() else "png"
        
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(img_url, timeout=10) as resp:
                    if resp.status != 200:
                        await ctx.send(f"Gagal download card (HTTP {resp.status})")
                        return
                    data = await resp.read()
                    file_data = io.BytesIO(data)
            await ctx.send(files=[File(file=file_data, file_name=f"{clean_name}.{file_ext}")])
        except Exception as e:
            await ctx.send(f"Error: {e}")
        return

    # Logika menu pilihan (jika parameter object kosong)
    unique_items = sorted(list(set(collection)))
    menu_options = [StringSelectOption(label=item, value=item) for item in unique_items[:25]]
    select_menu = StringSelectMenu(menu_options, placeholder="Pilih objek untuk melihat card...", custom_id="dex_list_select")

    await ctx.send(
        content=f"Kamu memiliki **{len(collection)}** objek. Pilih salah satu di bawah untuk melihat card-nya:",
        components=[ActionRow(select_menu)],
    )

@dex_list.autocomplete("object")
async def dex_list_autocomplete(ctx: AutocompleteContext):
    user_input = (ctx.input_text or "").lower()
    collection = user_collections.get(str(ctx.author.id), [])
    unique_items = sorted(list(set(collection)))
    results = [{"name": item, "value": item} for item in unique_items if user_input in item.lower()]
    try:
        await ctx.send(results[:25])
    except:
        pass

@component_callback("dex_list_select")
async def dex_list_select_callback(ctx: ComponentContext):
    selected_item = ctx.values[0]
    
    # reset nama jika shiny
    clean_name = selected_item.replace(" ✨", "")
    obj_data = find_object_by_name(clean_name)
    
    if not obj_data:
        await ctx.send(f"Objek **{selected_item}** tidak ditemukan.")
        return

    # Prioritaskan 'card', jika tidak ada baru gunakan 'image'
    card_url = obj_data.get("card") or obj_data.get("image")
    
    if not card_url:
        await ctx.send(f"Objek **{selected_item}** ini belum punya card.")
        return

    # defer karwna download bisa lama
    await ctx.defer()

    img_url = card_url
    file_ext = "gif" if img_url.lower().endswith(".gif") or ".gifv" in img_url.lower() else "png"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(img_url, timeout=10) as resp:
                if resp.status != 200:
                    await ctx.send(f"Gagal mendownload gambar untuk **{selected_item}** (HTTP {resp.status}).\nURL: {img_url}")
                    return
                data = await resp.read()
                file_data = io.BytesIO(data)
                
        # kirim card dari memori
        await ctx.send(
            files=[File(file=file_data, file_name=f"{clean_name}.{file_ext}")]
        )
    except Exception as e:
        await ctx.send(f"Terjadi kesalahan saat mengirim card: {str(e)}")

@dex.subcommand(
    sub_cmd_name="collections",
    sub_cmd_description="Lihat progres koleksi OsciDex milikmu"
)
async def dex_completions(ctx: SlashContext):
    user_id = str(ctx.author.id)
    collection = user_collections.get(user_id, [])

    if not collection:
        await ctx.send("Kamu belum punya objek apa pun :/\n-# skill issue :3")
        return

    unique_owned = sorted(set(collection))
    total_objects = len(OBJECTS)
    completion_percent = (len(unique_owned) / total_objects) * 100

    # Hitung jumlah terlebih dahulu untuk setiap nama untuk menghindari .count() yang berulang.
    items = []
    for name in unique_owned:
        items.append({"name": name, "count": collection.count(name)})

    await send_paginated_embed(
        ctx, 
        items, 
        f"OsciDex Completion — {ctx.author.username}", 
        f"Progress: **{len(unique_owned)}/{total_objects}** ({completion_percent:.1f}%)",
        is_user_collection=True
    )

async def send_paginated_embed(ctx, items, title, description, is_user_collection=False, page=0):
    chunk_size = 10
    total_pages = (len(items) + chunk_size - 1) // chunk_size

    start = page * chunk_size
    end = start + chunk_size
    chunk = items[start:end]

    embed = Embed(title=title, description=description, color=0x00FF00 if not is_user_collection else 0xFFD700)
    for item in chunk:
        if is_user_collection:
            embed.add_field(name=item["name"], value=f"Jumlah: **{item['count']}x**", inline=True)
        else:
            embed.add_field(name=item["name"], value=f"Rarity: **{item['rarity']}**", inline=True)

    embed.set_footer(text=f"Halaman {page + 1} dari {total_pages}")

    components = [
        ActionRow(
            Button(style=ButtonStyle.SECONDARY, label="<", custom_id=f"page_prev_{page}_{'coll' if is_user_collection else 'dex'}_{ctx.author.id}"),
            Button(style=ButtonStyle.SECONDARY, label=">", custom_id=f"page_next_{page}_{'coll' if is_user_collection else 'dex'}_{ctx.author.id}")
        )
    ]

    if hasattr(ctx, "edit_origin"):
        await ctx.edit_origin(embeds=embed, components=components)
    else:
        await ctx.send(embeds=embed, components=components)

@component_callback(re.compile(r"page_(prev|next)_\d+_(dex|coll)_\d+"))
async def page_callback(ctx: ComponentContext):
    parts = ctx.custom_id.split("_")
    action = parts[1]
    current_page = int(parts[2])
    type_ = parts[3]
    owner_id = int(parts[4])

    if ctx.author.id != owner_id:
        await ctx.send("Hanya pengirim perintah yang bisa mengganti halaman.", ephemeral=True)
        return

    new_page = current_page - 1 if action == "prev" else current_page + 1

    if type_ == "dex":
        items = OBJECTS
        title = "OsciDex Completions"
        description = "Daftar semua objek yang bisa kamu temukan!"
        is_user_collection = False
    else:
        user_id = str(owner_id)
        collection = user_collections.get(user_id, [])
        unique_owned = sorted(set(collection))
        total_objects = len(OBJECTS)
        completion_percent = (len(unique_owned) / total_objects) * 100
        items = [{"name": name, "count": collection.count(name)} for name in unique_owned]
        title = f"OsciDex Completion — {ctx.author.username}"
        description = f"Progress: **{len(unique_owned)}/{total_objects}** ({completion_percent:.1f}%)"
        is_user_collection = True

    total_pages = (len(items) + 10 - 1) // 10
    if new_page < 0 or new_page >= total_pages:
        await ctx.send("Sudah mencapai batas halaman.", ephemeral=True)
        return

    await send_paginated_embed(ctx, items, title, description, is_user_collection, new_page)



# ===================== BUTTONS =====================

@component_callback("catch_btn")
async def catch_button(ctx: ComponentContext):
    message_id = str(ctx.message.id)

    if message_id not in active_spawns:
        try:
            await ctx.send("Objek sudah expired.", ephemeral=True)
        except:
            pass
        return

    modal = Modal(
        ShortText(
            label="Nama objek",
            custom_id="guess",
            placeholder="Ketik nama objek",
            required=True
        ),
        title="Catch the Object!",
        custom_id=f"catch_modal:{message_id}"
    )

    try:
        await ctx.send_modal(modal)
    except Exception as e:
        print(f"Failed to send modal: {e}")

@component_callback("rarity_btn")
async def rarity_button(ctx: ComponentContext):
    message_id = str(ctx.message.id)
    spawn = active_spawns.get(message_id)
    if not spawn:
        try:
            await ctx.send("Objek sudah expired.", ephemeral=True)
        except:
            pass
        return

    obj = spawn["object"]
    try:
        await ctx.send(
            f"Rarity objek ini adalah **{obj['rarity']}**\nSemakin kecil angkanya semakin langka.",
            ephemeral=True
        )
    except:
        pass


# ===================== MODAL =====================

@modal_callback(re.compile(r"^catch_modal:\d+$"))
async def on_modal(ctx, guess: str):
    message_id = ctx.custom_id.split(":")[1]
    spawn = active_spawns.get(message_id)

    if not spawn:
        await ctx.send("Objek sudah expired.", ephemeral=True)
        return

    obj_name = spawn["object"]["name"]

    if normalize_name(guess) != normalize_name(obj_name):
        await ctx.send(
            f"<@{ctx.author.id}> salah bro! Kamu ngetik `{guess}`",
            ephemeral=True
        )
        return


    user_id = str(ctx.author.id)
    object_name = spawn["object"]["name"]
    obj_color = spawn["object"]["color"]
    is_shiny = spawn.get("is_shiny", False)

    # Periksa apakah ini objek baru bagi user
# Shiny dianggap sebagai "tipe" yang berbeda untuk tujuan pesan
    storage_name = f"{object_name} ✨" if is_shiny else object_name
    is_new = storage_name not in user_collections.get(user_id, [])

    add_to_collection(user_id, storage_name)

    if is_shiny:
        status_text = "objek shiny"
    else:
        status_text = "objek baru" if is_new else "objek duplikat"

    message_content = f"<@{ctx.author.id}> kau menangkap **{storage_name}** `(#{obj_color}, +0%/+0%)`\n\n Ini adalah **{status_text}** yang ditambahkan ke koleksimu!"

    try:
        await ctx.send(message_content, ephemeral=False)
    except:
        # Jika ctx.send gagal karena interaction expired/already acknowledged, gunakan channel.send
        await ctx.channel.send(message_content)

    active_spawns.pop(message_id, None)
    
    # Update pesan spawn untuk mendisable button setelah ditangkap
    try:
        spawn_msg = await ctx.channel.fetch_message(int(message_id))
        await spawn_msg.edit(components=disabled_components())
    except:
        pass

# ===================== READY =====================

@listen()
async def on_ready():
    print(f"OsciDex online sebagai {client.user.tag}")

    # print untuk auto spawn channels
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

client.start(os.getenv("DISCORD_TOKEN"))
