import os
import discord
from discord.ext import commands
import asyncio
import requests
import re

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

TC_SEARCH_URL = "https://tc-ffxiv-item-search-service.onrender.com/items/search"
XIVAPI_SEARCH_URL = "https://v2.xivapi.com/api/search"
UNIVERSALIS_URL = "https://universalis.app/api/v2"

TC_WORLDS = [
    "巴哈姆特",
    "鳳凰",
    "泰坦",
    "伊弗利特",
    "迦樓羅",
    "利維坦",
    "奧汀",
]


def search_tc(query):
    params = {
        "sheets": "Items",
        "query": query,
        "language": "tc",
        "limit": 100,
        "field": "Name,ItemSearchCategory.Name,Icon,LevelItem.todo,Rarity"
    }

    headers = {
        "origin": "https://universalis.app",
        "referer": "https://universalis.app/",
        "user-agent": "Mozilla/5.0"
    }

    r = requests.get(TC_SEARCH_URL, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def search_en(query):
    params = {
        "sheets": "Item",
        "query": f'+Name~"{query}"',
        "language": "en",
        "limit": 100,
        "fields": "Name"
    }

    r = requests.get(XIVAPI_SEARCH_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def is_english_query(query):
    query = query.strip()
    return re.search(r"[\u4e00-\u9fff]", query) is None


def pick_items(data, query, top_n=3):
    if "items" in data:
        items = data.get("items", [])

        exact = [x for x in items if x.get("name") == query]
        if exact:
            return exact[:top_n]

        return items[:top_n]

    if "results" in data:
        results = data.get("results", [])

        normalized = []
        for x in results:
            row_id = x.get("row_id")
            name = x.get("fields", {}).get("Name")

            if row_id and name:
                normalized.append({
                    "id": row_id,
                    "name": name
                })

        exact = [x for x in normalized if x.get("name", "").lower() == query.lower()]
        if exact:
            return exact[:top_n]

        return normalized[:top_n]

    return []


def get_price(world_name, item_id, listings=5):
    url = f"{UNIVERSALIS_URL}/{world_name}/{item_id}"
    params = {"listings": listings}

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def format_all_worlds(world_data):
    lines = []
    all_has_hq = False

    for world_name, data in world_data:
        listings = data.get("listings", [])

        lines.append(f"【{world_name}】")

        if not listings:
            lines.append("  沒有掛單資料")
            lines.append("")
            continue

        for i, x in enumerate(listings[:5], 1):
            price = f"{x.get('pricePerUnit', 0):,}"
            qty = x.get("quantity", 0)
            is_hq = x.get("hq", False)

            if is_hq:
                all_has_hq = True

            hq_tag = "HQ " if is_hq else ""
            lines.append(f"  {i}. {hq_tag}{price} ({qty}個)")

        lines.append("")

    if not all_has_hq:
        lines.insert(0, "")
        lines.insert(0, "（以下皆無HQ商品）")

    return lines


def full_search_tc_worlds_text(query):
    if is_english_query(query):
        data = search_en(query)
    else:
        data = search_tc(query)

    picked = pick_items(data, query, top_n=3)

    if not picked:
        return f"找不到「{query}」"

    item = picked[0]

    world_data = []
    for world_name in TC_WORLDS:
        try:
            market = get_price(world_name, item["id"], listings=5)
            world_data.append((world_name, market))
        except Exception:
            world_data.append((world_name, {"listings": []}))

    lines = []
    lines.append(f"物品：{item['name']} | ID：{item['id']}")
    lines.append("-" * 30)
    lines.extend(format_all_worlds(world_data))

    return "\n".join(lines).strip()


def extract_query(text):
    text = text.strip()
    text = re.sub(r"(查價|價格|物價|查)", "", text)
    return text.strip()


def is_price_query(text):
    keywords = ["查價", "價格", "物價", "查"]
    text = text.strip()

    if any(k in text for k in keywords):
        return True

    if len(text) <= 20:
        return True

    return False


@bot.event
async def on_ready():
    print(f"Bot 已上線：{bot.user}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if not message.content:
        return

    if bot.user not in message.mentions:
        return

    text = message.content.replace(f"<@{bot.user.id}>", "")
    text = text.replace(f"<@!{bot.user.id}>", "")
    text = text.strip()

    if not text:
        await message.channel.send(
            f"{message.author.mention} 哈比卜，報上物品名字，我替你看各世界價格。",
            allowed_mentions=discord.AllowedMentions(users=True)
        )
        return

    if is_price_query(text):
        query = extract_query(text)

        if not query:
            await message.channel.send(
                f"{message.author.mention} 哈比卜，至少說個物品名字。",
                allowed_mentions=discord.AllowedMentions(users=True)
            )
            return

        try:
            result = await asyncio.to_thread(full_search_tc_worlds_text, query)

            if len(result) > 1900:
                chunks = [result[i:i + 1900] for i in range(0, len(result), 1900)]
                for chunk in chunks:
                    await message.channel.send(
                        f"{message.author.mention}\n```{chunk}```",
                        allowed_mentions=discord.AllowedMentions(users=True)
                    )
            else:
                await message.channel.send(
                    f"{message.author.mention}\n```{result}```",
                    allowed_mentions=discord.AllowedMentions(users=True)
                )

        except Exception as e:
            await message.channel.send(
                f"{message.author.mention} 查詢失敗：{e}",
                allowed_mentions=discord.AllowedMentions(users=True)
            )

        return

    await message.channel.send(
        f"{message.author.mention} 哈比卜，我的朋友，說出物品名，我幫你查價。",
        allowed_mentions=discord.AllowedMentions(users=True)
    )


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("請先設定環境變數 DISCORD_BOT_TOKEN")
    bot.run(TOKEN)
