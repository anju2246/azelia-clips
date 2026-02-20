# Customizing Celia Clips

Celia Clips allows you to override default behaviors without modifying the source code. This is perfect for maintaining your podcast's unique voice and style while keeping the core software up to date.

## 1. Custom Prompts

 You can provide your own instructions to the AI agents by placing text files in your **Podcast Directory**.

### Location
Create a folder named `prompts` inside your configured podcast directory:
`{PODCAST_DIR}/prompts/`

### Available Overrides
Create files with these exact names to override specific agents:

| Filename | Agent | Purpose |
| :--- | :--- | :--- |
| `finder_prompt.txt` | **Finder** | Rules for finding potential clips. Good for specifying topics to ignore or prioritize. |
| `critic_prompt.txt` | **Critic** | Quality control standards. Use this to enforce stricter or looser filtering. |
| `ranker_prompt.txt` | **Ranker** | Scoring criteria. Adjust this to prioritize "funny" vs "informative" clips. |
| `caption_prompt.txt` | **Caption Generator** | The heavy lifter. Defines the voice, tone, emoji usage, and hashtag strategy for your social posts. |

### Example: Custom Caption Prompt
**File:** `.../MyPodcast/prompts/caption_prompt.txt`
```text
You are the social media manager for "{podcast_name}".
Create a LinkedIn post for this clip using our brand voice: professional but provocative.

Clip Context:
Title: {clip_title}
Summary: {clip_summary}
Transcript: {clip_text}

Requirements:
1. Start with a contrarian hook.
2. Use short paragraphs.
3. End with a question.
4. Use these hashtags: #MyBrand #{clip_category}
```

## 2. Subtitle Styles (Coming Soon)
Future updates will allow loading `styles.json` from your podcast directory to define custom fonts and colors.

## 3. Configuration
Your podcast name and directory are configured in the **Settings** page of the web dashboard.
