import os
import discord
from discord.ext import commands
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from dotenv import load_dotenv
from datetime import datetime
import hashlib
import hmac
import secrets
import json
import requests

# Load environment variables from .env file
load_dotenv()

# Discord Bot Token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Bitcoin RPC setup
rpc_user = os.getenv("BITCOIN_RPC_USER")
rpc_password = os.getenv("BITCOIN_RPC_PASSWORD")
rpc_host = os.getenv("BITCOIN_RPC_HOST")
rpc_port = os.getenv("BITCOIN_RPC_PORT")
rpc_url = f"http://{rpc_user}:{rpc_password}@{rpc_host}:{rpc_port}"
bitcoin_rpc = AuthServiceProxy(rpc_url)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

Base = declarative_base()

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True, index=True)
    balance = Column(Float, default=0.0)
    otp_secret = Column(String, nullable=False)

class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True)
    pot = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    players = relationship("Player", secondary="game_players")

class GamePlayer(Base):
    __tablename__ = 'game_players'
    game_id = Column(Integer, ForeignKey('games.id'), primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'), primary_key=True)
    bet_amount = Column(Float, default=0.0)

Base.metadata.create_all(engine)

# Initialize the bot
bot = commands.Bot(command_prefix="!")

def generate_otp_secret():
    return secrets.token_hex(16)

def verify_otp(secret, otp_code):
    # Simple OTP verification (to be replaced with a more robust solution)
    return hmac.compare_digest(secret, otp_code)

@bot.event
async def on_ready():
    print(f'Bot is ready as {bot.user}')

@bot.command()
async def join(ctx):
    player_id = str(ctx.author.id)
    if not session.query(Player).filter_by(discord_id=player_id).first():
        otp_secret = generate_otp_secret()
        new_player = Player(discord_id=player_id, otp_secret=otp_secret)
        session.add(new_player)
        session.commit()
        await ctx.send(f'{ctx.author.name} has joined the game! Your OTP secret: {otp_secret}')
    else:
        await ctx.send(f'{ctx.author.name} is already in the game.')

@bot.command()
async def balance(ctx):
    player_id = str(ctx.author.id)
    player = session.query(Player).filter_by(discord_id=player_id).first()
    if player:
        await ctx.send(f"Your balance is {player.balance} BTC.")
    else:
        await ctx.send("You need to join the game first using !join")

@bot.command()
async def deposit(ctx, address: str, amount: float, otp_code: str):
    player_id = str(ctx.author.id)
    player = session.query(Player).filter_by(discord_id=player_id).first()
    if player:
        if verify_otp(player.otp_secret, otp_code):
            try:
                txid = bitcoin_rpc.sendtoaddress(address, amount)
                player.balance += amount
                session.commit()
                await ctx.send(f"Deposit successful! {amount} BTC added to your balance. Transaction ID: {txid}")
            except JSONRPCException as e:
                await ctx.send(f"Transaction failed: {str(e)}")
        else:
            await ctx.send("Invalid OTP code.")
    else:
        await ctx.send("You need to join the game first using !join")

@bot.command()
async def bet(ctx, amount: float, otp_code: str):
    player_id = str(ctx.author.id)
    player = session.query(Player).filter_by(discord_id=player_id).first()
    if player:
        if verify_otp(player.otp_secret, otp_code):
            if player.balance >= amount:
                game = session.query(Game).first()
                if not game:
                    game = Game()
                    session.add(game)
                    session.commit()

                player.balance -= amount
                game.pot += amount

                game_player = GamePlayer(game_id=game.id, player_id=player.id, bet_amount=amount)
                session.add(game_player)

                session.commit()
                await ctx.send(f"{ctx.author.name} bet {amount} BTC. Current pot: {game.pot} BTC.")
            else:
                await ctx.send("Insufficient balance.")
        else:
            await ctx.send("Invalid OTP code.")
    else:
        await ctx.send("You need to join the game first using !join")

@bot.command()
async def win(ctx):
    player_id = str(ctx.author.id)
    player = session.query(Player).filter_by(discord_id=player_id).first()
    if player:
        game = session.query(Game).first()
        if game and game.pot > 0:
            # Smart contract logic would replace the following in a real implementation
            player.balance += game.pot
            game.pot = 0
            session.commit()
            await ctx.send(f"{ctx.author.name} wins the pot! Your new balance is {player.balance} BTC.")
        else:
            await ctx.send("There is no active pot.")
    else:
        await ctx.send("You need to join the game first using !join")

@bot.command()
async def stats(ctx):
    top_players = session.query(Player).order_by(Player.balance.desc()).limit(10).all()
    leaderboard = "\n".join([f"{i+1}. {player.discord_id}: {player.balance} BTC" for i, player in enumerate(top_players)])
    await ctx.send(f"Top Players:\n{leaderboard}")

@bot.command()
async def monitor_tx(ctx, txid: str):
    url = f"https://blockchain.info/rawtx/{txid}"
    response = requests.get(url)
    if response.status_code == 200:
        tx_info = response.json()
        await ctx.send(f"Transaction {txid} details: {json.dumps(tx_info, indent=2)}")
    else:
        await ctx.send(f"Could not retrieve transaction information for {txid}")

@bot.command()
async def audit(ctx):
    all_players = session.query(Player).all()
    audit_report = "\n".join([f"Player {player.discord_id}: {player.balance} BTC" for player in all_players])
    await ctx.send(f"Audit Report:\n{audit_report}")

# Run the bot
bot.run(DISCORD_TOKEN)
