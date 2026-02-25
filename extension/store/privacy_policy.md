# Privacy Policy for AutoApply AI Chrome Extension

**Last updated:** February 2026

## Overview

AutoApply AI ("the Extension") is a personal productivity tool that helps you manage and apply job applications. This privacy policy explains what data the Extension collects, how it's used, and how it's protected.

## Data We Collect

### Data You Provide
- **Resume files**: Uploaded by you to your own backend instance. Stored in your personal PostgreSQL database and your own private GitHub repository.
- **API keys**: LLM API keys (Anthropic, OpenAI, etc.) are stored locally in `chrome.storage.local` on your device only. They are never transmitted to any third-party server other than the LLM provider you choose.
- **Authentication token**: Your Clerk user ID, stored in `chrome.storage.local`.

### Data Detected Automatically
- **Page URL and title**: Used to determine if you're on a job application page. Never stored or transmitted beyond the extension's service worker.
- **Form fields on the current page**: Detected to suggest auto-fill values. This data exists only in memory and is discarded when you navigate away.
- **Job listing cards**: Scraped from LinkedIn/Indeed for Job Scout mode. Used only to display match scores; never stored.

## Data Storage

| Data | Where Stored |
|------|-------------|
| Resume files and text | Your own database (self-hosted or Render) |
| Application answers | Your own database |
| GitHub token | Your own database (encrypted with Fernet) |
| LLM API key | Your device (`chrome.storage.local`) |
| Auth token (Clerk user ID) | Your device (`chrome.storage.local`) |

**AutoApply AI never stores your data on servers it controls.** The backend is either self-hosted by you or deployed to a cloud account you own.

## Data Sharing

We do not sell, trade, or share your personal data with any third parties, except:
- **LLM providers** (Anthropic, OpenAI, etc.): Only when you explicitly trigger resume generation or Q&A generation. The text sent consists of job descriptions and work history you provide.
- **Clerk**: For user authentication. Subject to [Clerk's privacy policy](https://clerk.com/privacy).
- **GitHub**: For storing your resume files. Subject to [GitHub's privacy policy](https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement).

## Permissions Used

| Permission | Purpose |
|-----------|---------|
| `sidePanel` | Display the AutoApply AI sidebar |
| `storage` | Save settings and auth token locally |
| `tabs` | Detect active tab URL for job page recognition |
| `activeTab` | Read current page content for field detection |
| `scripting` | Inject content script to detect form fields |

## Contact

This extension is an open-source personal productivity tool. For questions or concerns, open an issue on the project's GitHub repository.
