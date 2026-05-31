# Smart Cart — Home Assistant Add-on

AI-powered shopping assistant for Home Assistant. Compares prices across Coles, Woolworths and Aldi, manages your recipes and shopping list, and helps you find the best deal each week.

## Features
- 📋 Persistent shopping list with categories, brand preferences and purchase history
- 🍽 Recipe library — add via URL, cookbook photo, or manual entry
- 🛒 Price comparison across Coles, Woolworths and Aldi
- 💰 Woolworths Rewards Plus 10% discount support
- 📊 Shop history and savings analytics
- 🔵 Aldi in-store checklist (persists until complete)

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**
2. Click the **⋮ menu** (top right) → **Repositories**
3. Add: `https://github.com/YOUR_GITHUB_USERNAME/smart-cart-addon`
4. Find **Smart Cart** in the store and click **Install**
5. In the add-on configuration, enter your **Claude API key** (from console.anthropic.com)
6. Click **Start**

## Configuration

| Option | Description |
|---|---|
| `claude_api_key` | Your Anthropic API key (required) |
| `preferred_delivery_window` | morning / afternoon / evening / any |
| `split_threshold` | Minimum $ saving to split between stores (default 10) |

## Getting a Claude API Key
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up and add a credit card
3. Click **API Keys → Create Key**
4. Copy the key and paste it into the add-on configuration

Usage costs approximately $1–2 AUD/month for typical weekly shopping use.
