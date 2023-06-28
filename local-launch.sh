#!/usr/bin/env bash
source .env

function handle_interrupt(){
  # TODO: might not be cross-platform? try killing the specific process, not the 'ngrok'
  killall ngrok

  rm .output
  trap SIGINT
  exit

}
trap handle_interrupt INT

# Start the background process and redirect its output to a file
python run_locally.py > .output &

# Wait for the first occurrence of a tunnel's public url using grep -m1
NGROK_URL=$(tail -f .output | grep -m1 "https")

# Setup webhooks
curl -F "url=$NGROK_URL/telegram_endpoint" "https://api.telegram.org/bot$TG_BOT_TOKEN/setWebhook?secret_token=$TG_SECRET_TOKEN"
# Start server
python main.py

killall ngrok
rm .output
trap SIGINT