import json
import os
import re
from datetime import datetime, timedelta
from urllib.request import urlopen
from urllib.error import URLError

LOG_FILE = "time_logs.json"
INTENT_MEMORY_FILE = "intent_memory.json"


class TimeTrackerBot:
    def __init__(self):
        self.logs = self.load_logs()
        self.intent_memory = self.load_intent_memory()
        self.pending_entry = {"project": None, "hours": None, "description": None}
        self.awaiting_field = None
        self.external_context = {}

    def load_logs(self):
        if not os.path.exists(LOG_FILE):
            return []
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_logs(self):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.logs, f, indent=2)

    def load_intent_memory(self):
        if not os.path.exists(INTENT_MEMORY_FILE):
            return []
        try:
            with open(INTENT_MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_intent_memory(self):
        with open(INTENT_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.intent_memory, f, indent=2)

    def refresh_external_context(self):
        ctx = {}
        sources = [
            ("time", "http://worldtimeapi.org/api/timezone/Etc/UTC"),
            ("ip", "https://api.ipify.org?format=json"),
        ]
        for key, url in sources:
            try:
                with urlopen(url, timeout=5) as resp:
                    data = resp.read().decode("utf-8")
                    ctx[key] = json.loads(data)
            except (URLError, ValueError, TimeoutError):
                ctx[key] = None
        self.external_context = ctx

    def run(self):
        print("Hi, I'm your time-tracking chatbot with a bit of learning and live context.")
        print("You can say things like: 'I worked 2h on Alpha', 'show today', or 'help'.\n")

        while True:
            user = input("You: ").strip()
            if not user:
                continue

            self.refresh_external_context()

            if self.awaiting_field:
                self.handle_pending_field(user)
                continue

            learned_intent = self.predict_intent_from_memory(user)
            if learned_intent is None:
                intent = self.detect_intent_rule_based(user)
            else:
                intent = learned_intent

            if intent == "exit":
                print("Bot: Okay, goodbye! Your time logs are saved.")
                self.save_logs()
                break
            elif intent == "help":
                self.handle_help()
            elif intent == "log_time":
                self.handle_log_time(user)
            elif intent == "show_summary":
                self.handle_show_summary(user)
            else:
                self.handle_unknown(user)

            self.remember_intent(user, intent)

    def detect_intent_rule_based(self, text):
        t = text.lower()
        if any(w in t for w in ["exit", "quit", "bye"]):
            return "exit"
        if "help" in t:
            return "help"
        if any(w in t for w in ["summary", "show", "report", "what did i do"]):
            return "show_summary"
        if any(w in t for w in ["log", "worked", "spent", "track", "time on"]):
            return "log_time"
        return "unknown"

    def text_to_wordset(self, text):
        words = re.findall(r"[a-zA-Z]+", text.lower())
        return set(words)

    def jaccard_similarity(self, set_a, set_b):
        if not set_a or not set_b:
            return 0.0
        inter = len(set_a & set_b)
        union = len(set_a | set_b)
        if union == 0:
            return 0.0
        return inter / union

    def predict_intent_from_memory(self, text):
        if not self.intent_memory:
            return None
        current_words = self.text_to_wordset(text)
        best_score = 0.0
        best_intent = None
        for item in self.intent_memory:
            past_words = self.text_to_wordset(item["text"])
            score = self.jaccard_similarity(current_words, past_words)
            if score > best_score:
                best_score = score
                best_intent = item["intent"]
        if best_score >= 0.4:
            return best_intent
        return None

    def remember_intent(self, text, intent):
        self.intent_memory.append({"text": text, "intent": intent})
        self.save_intent_memory()

    def handle_help(self):
        utc_info = self.external_context.get("time")
        ip_info = self.external_context.get("ip")
        utc_str = None
        if isinstance(utc_info, dict):
            utc_str = utc_info.get("utc_datetime")
        ip_str = None
        if isinstance(ip_info, dict):
            ip_str = ip_info.get("ip")
        extra = []
        if utc_str:
            extra.append(f"current UTC time is {utc_str}")
        if ip_str:
            extra.append(f"your public IP looks like {ip_str}")
        extra_text = ""
        if extra:
            extra_text = " (" + "; ".join(extra) + ")"
        print("Bot: I can help you track your hours" + extra_text + ".")
        print("  - 'I worked 2h on Project Alpha fixing bugs'")
        print("  - 'log 1.5 hours on website redesign'")
        print("  - 'show today' or 'show this week'")
        print("  - 'summary' to see all logs")
        print("  - 'exit' to quit")

    def handle_log_time(self, text):
        hours = self.extract_hours(text)
        project = self.extract_project(text)
        description = self.extract_description(text, project)
        self.pending_entry = {"project": project, "hours": hours, "description": description}
        if self.pending_entry["hours"] is None:
            self.awaiting_field = "hours"
            print("Bot: How many hours did you work?")
            return
        if self.pending_entry["project"] is None:
            self.awaiting_field = "project"
            print("Bot: What project was this for?")
            return
        if self.pending_entry["description"] is None:
            self.awaiting_field = "description"
            print("Bot: Can you add a short description of what you did?")
            return
        self.commit_pending_entry()

    def handle_pending_field(self, user):
        field = self.awaiting_field
        if field == "hours":
            hours = self.extract_hours(user)
            if hours is None:
                print("Bot: I couldn't understand the hours. Try something like '2' or '1.5 hours'.")
                return
            self.pending_entry["hours"] = hours
        elif field == "project":
            self.pending_entry["project"] = user.strip()
        elif field == "description":
            self.pending_entry["description"] = user.strip()
        self.awaiting_field = None
        missing = [k for k, v in self.pending_entry.items() if v is None]
        if not missing:
            self.commit_pending_entry()
        else:
            next_field = missing[0]
            self.awaiting_field = next_field
            if next_field == "hours":
                print("Bot: How many hours did you work?")
            elif next_field == "project":
                print("Bot: What project was this for?")
            elif next_field == "description":
                print("Bot: Can you add a short description of what you did?")

    def commit_pending_entry(self):
        entry = dict(self.pending_entry)
        entry["timestamp"] = datetime.utcnow().isoformat(timespec="seconds")
        self.logs.append(entry)
        self.save_logs()
        print(f"Bot: Logged {entry['hours']}h on '{entry['project']}' - {entry['description']}.")
        self.pending_entry = {"project": None, "hours": None, "description": None}
        self.awaiting_field = None

    def extract_hours(self, text):
        pattern = r"(\d+(\.\d+)?)\s*(h|hr|hrs|hour|hours)?"
        matches = re.findall(pattern, text.lower())
        if not matches:
            return None
        try:
            return float(matches[0][0])
        except ValueError:
            return None

    def extract_project(self, text):
        lower = text.lower()
        for kw in [" on ", " for "]:
            if kw in lower:
                idx = lower.index(kw) + len(kw)
                project_part = text[idx:].strip()
                stop_words = [" fixing", " doing", " working", " for ", " on "]
                cut_idx = len(project_part)
                for sw in stop_words:
                    pos = project_part.lower().find(sw)
                    if pos != -1:
                        cut_idx = min(cut_idx, pos)
                project = project_part[:cut_idx].strip(",. ")
                if project:
                    return project
        return None

    def extract_description(self, text, project):
        desc = text.strip()
        if project:
            desc = desc.replace(project, "").strip()
        if len(desc.split()) < 3:
            return None
        return desc

    def handle_show_summary(self, text):
        t = text.lower()
        now = datetime.utcnow()
        if "today" in t:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            label = "today"
        elif "week" in t:
            start = now - timedelta(days=7)
            label = "the last 7 days"
        else:
            start = None
            label = "all time"
        filtered = self.filter_logs(start)
        if not filtered:
            print(f"Bot: No logs found for {label}.")
            return
        total_hours = sum(e["hours"] for e in filtered)
        utc_info = self.external_context.get("time")
        utc_str = None
        if isinstance(utc_info, dict):
            utc_str = utc_info.get("utc_datetime")
        header_extra = f" (current UTC: {utc_str})" if utc_str else ""
        print(f"Bot: Here's your summary for {label}{header_extra}:")
        print(f"  Total hours: {total_hours:.2f}")
        by_project = {}
        for e in filtered:
            by_project.setdefault(e["project"], 0.0)
            by_project[e["project"]] += e["hours"]
        for project, hours in by_project.items():
            print(f"  - {project}: {hours:.2f}h")

    def filter_logs(self, start_dt):
        if start_dt is None:
            return self.logs
        result = []
        for e in self.logs:
            try:
                ts = datetime.fromisoformat(e["timestamp"])
            except Exception:
                continue
            if ts >= start_dt:
                result.append(e)
        return result

    def handle_unknown(self, text):
        utc_info = self.external_context.get("time")
        ip_info = self.external_context.get("ip")
        utc_str = utc_info.get("utc_datetime") if isinstance(utc_info, dict) else None
        ip_str = ip_info.get("ip") if isinstance(ip_info, dict) else None
        extra = []
        if utc_str:
            extra.append(f"UTC now is {utc_str}")
        if ip_str:
            extra.append(f"your IP looks like {ip_str}")
        extra_text = ""
        if extra:
            extra_text = " " + "; ".join(extra)
        print("Bot: I'm not sure what you mean. Try 'help' to see what I can do." + extra_text)


if __name__ == "__main__":
    bot = TimeTrackerBot()
    bot.run()
