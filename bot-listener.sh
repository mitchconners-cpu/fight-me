#!/bin/bash

TOKEN="8881701685:AAFJF8E8YPt7gjF1uamS8W9lKM5sKrGXYx4"
OFFSET=0
DB="wager_bot.db"

# Replace with your active ngrok forwarding URL
WEB_URL="https://YOUR-NGROK-SUBDOMAIN.ngrok-free.app"

echo "🚀 Gateway Wagering Bot Listener Started..."

while true; do
  RESPONSE=$(curl -s "https://api.telegram.org/bot$TOKEN/getUpdates?offset=$OFFSET&timeout=30")
  UPDATE_IDS=$(echo "$RESPONSE" | jq '.result[].update_id' 2>/dev/null)
  
  if [ -n "$UPDATE_IDS" ]; then
    for ID in $UPDATE_IDS; do
      TEXT=$(echo "$RESPONSE" | jq -r --argjson id "$ID" '.result[] | select(.update_id == $id) | .message.text // empty')
      SENDER_ID=$(echo "$RESPONSE" | jq -r --argjson id "$ID" '.result[] | select(.update_id == $id) | .message.chat.id // empty')
      
      if [ -n "$TEXT" ]; then
        echo "📩 Received [from $SENDER_ID]: $TEXT"
        
        # Fetch user state and btc address from SQLite
        USER_INFO=$(sqlite3 "$DB" "SELECT state, btc_address FROM users WHERE chat_id='$SENDER_ID';")
        STATE=$(echo "$USER_INFO" | cut -d'|' -f1)
        BTC_ADDR=$(echo "$USER_INFO" | cut -d'|' -f2)
        
        if [ -z "$STATE" ]; then
          STATE="IDLE"
          sqlite3 "$DB" "INSERT OR IGNORE INTO users (chat_id, state) VALUES ('$SENDER_ID', 'IDLE');"
        fi

        RESPONSE_TEXT=""

        # Command Routing & Gateway Menu
        if [ "$TEXT" = "/start" ]; then
          sqlite3 "$DB" "UPDATE users SET state='AWAITING_BTC' WHERE chat_id='$SENDER_ID';"
          RESPONSE_TEXT="🌐 **Welcome to the Wagering Gateway** 🚀%0A%0APlease reply with your **Bitcoin address** to authenticate and access your account:"

        elif [ "$STATE" = "AWAITING_BTC" ]; then
          sqlite3 "$DB" "UPDATE users SET btc_address='$TEXT', state='LOGGED_IN' WHERE chat_id='$SENDER_ID';"
          RESPONSE_TEXT="✅ **Authentication Successful!**%0ABTC: \`$TEXT\`%0A%0A📋 **Gateway Options:**%0A• /wagers - View active pools & participation%0A• /create - Launch a new wage (10% fee applies)%0A• /home - Open mobile web app via ngrok%0A• /start - Re-authenticate"

        elif [ "$TEXT" = "/wagers" ]; then
          if [ "$STATE" != "LOGGED_IN" ]; then
            RESPONSE_TEXT="⚠️ Please type /start first to authenticate with your Bitcoin address."
          else
            ONGOING=$(sqlite3 "$DB" "SELECT name, amount FROM wagers WHERE status='Open';" | awk -F'|' '{print "• " $1 " (Pool: " $2 " BTC)"}' | paste -sd "%0A" -)
            RESPONSE_TEXT="📊 **Gateway Dashboard**%0ABTC: \`$BTC_ADDR\`%0A%0A**Ongoing Wager Pools:**%0A$ONGOING%0A%0A👉 **Proceed with:**%0A/create - Create a new wage%0A/home - Open mobile web app"
          fi

        elif [ "$TEXT" = "/create" ]; then
          if [ "$STATE" != "LOGGED_IN" ]; then
            RESPONSE_TEXT="⚠️ Please type /start first to authenticate."
          else
            sqlite3 "$DB" "UPDATE users SET state='AWAITING_CREATE_NAME' WHERE chat_id='$SENDER_ID';"
            RESPONSE_TEXT="🛠️ **Create New Wage**%0A%0APlease enter a name/title for the new wage:"
          fi

        elif [ "$TEXT" = "/home" ] || [ "$TEXT" = "/app" ]; then
          if [ "$STATE" != "LOGGED_IN" ]; then
            RESPONSE_TEXT="⚠️ Please type /start first to authenticate."
          else
            RESPONSE_TEXT="📱 **Mobile Web Application (Ngrok Gateway)**%0A%0ATap the link below to open your mobile interface:%0A%0A[Launch Mobile Web App]($WEB_URL)"
          fi

        elif [ "$STATE" = "AWAITING_CREATE_NAME" ]; then
          sqlite3 "$DB" "UPDATE users SET state='AWAITING_CREATE_AMOUNT:$TEXT' WHERE chat_id='$SENDER_ID';"
          RESPONSE_TEXT="💰 Great. Now, how much do you want to wager on **$TEXT** (in BTC)?"

        elif [[ "$STATE" == AWAITING_CREATE_AMOUNT* ]]; then
          WAGE_NAME=$(echo "$STATE" | cut -d: -f2)
          WAGER_AMOUNT="$TEXT"
          
          # Calculate 10% platform fee using bc
          FEE=$(echo "$WAGER_AMOUNT * 0.10" | bc -l)
          NET_AMOUNT=$(echo "$WAGER_AMOUNT - $FEE" | bc -l)

          # Save new wage into SQLite database permanently
          sqlite3 "$DB" "INSERT INTO wagers (name, amount, creator_chat_id, status) VALUES ('$WAGE_NAME', '$WAGER_AMOUNT', '$SENDER_ID', 'Open');"

          # Reset user state back to logged in
          sqlite3 "$DB" "UPDATE users SET state='LOGGED_IN' WHERE chat_id='$SENDER_ID';"

          RESPONSE_TEXT="🎉 Wage **$WAGE_NAME** created successfully!%0A- Total Wager: $WAGER_AMOUNT BTC%0A- App Fee (10%): $FEE BTC%0A- Net Pool: $NET_AMOUNT BTC%0A%0AUse /wagers to view the updated pool list."
        else
          RESPONSE_TEXT="🤖 **Gateway Menu Options:**%0A• /wagers - View active wagers%0A• /create - Create new wage%0A• /home - Open mobile web app%0A• /start - Reset session"
        fi

        # Send response back via Markdown
        curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
          -d "chat_id=$SENDER_ID" \
          -d "parse_mode=Markdown" \
          -d "text=$RESPONSE_TEXT" > /dev/null
      fi
      
      OFFSET=$((ID + 1))
    done
  fi
  
  sleep 2
done
