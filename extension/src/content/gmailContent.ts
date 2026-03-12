/**
 * gmailContent.ts — T2: Gmail content script entry point
 * Injected only on mail.google.com.
 * Initializes the Gmail email-status tracker.
 */
import { initGmailTracker } from "./gmailTracker";

initGmailTracker();

export {};
