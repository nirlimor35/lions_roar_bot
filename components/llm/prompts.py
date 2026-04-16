class Prompts:
    CLOSED_INCIDENT_SUBJECT_RESPONSE = '{{"subject": string}}'
    FIRST_PROMPT_RESPONSE = '{{"response_message": string in Hebrew only with no emojis, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high"}}'
    ONGOING_PROMPT_RESPONSE = '{{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high", "related": boolean, "ended": boolean, "close_reason": string|null, "subject": string}}'

    PRIORITY_AREAS = (
        "המרכז (central Israel) — גבעתיים (Givatayim), גוש דן (Gush Dan). "
        'Givatayim is in the Central District; rockets or salvo focus "למרכז/מיקוד למרכז/המרכז" '
        "are in-scope for this user)"
    )
    PRIORITY_SCALE = (
        "Priority levels:\n"
        "- none: Unqualified — not relevant or scope is outside the priority areas.\n"
        "- informational: Threat explicitly at a named city in גוש דן / המרכז (e.g. רמת גן, פתח תקווה, הרצליה, בני ברק) that is NOT גבעתיים.\n"
        "- warning: Active home-front threat where the affected area is unconfirmed or still being clarified — including **launch-origin-only** lines (e.g. שיגורים מאיראן, טילים מלבנון) with **no** named Israeli destination, corridor, מיקוד, ETA, or city toward גבעתיים/גוש דן/המרכז in that same message. Default **warning** for those openers, not high. A line that **does** name a non-priority Israeli region as the aim (e.g. **לצפון הארץ**, **באזור הצפון**) is **not** origin-only — use priority **none** with qualified=false per DISQUALIFIERS.\n"
        "- high: Only when this same message clearly indicates danger or trajectory **toward** the priority areas (גבעתיים / גוש דן / המרכז / Tel Aviv metro): e.g. **generic** corridor/region without naming a specific non-Givatayim city — למרכז, מיקוד למרכז (המרכז as a region), לגוש דן, שיגורים בדרך toward that corridor, חדירה/אזעקה/ETA naming **the region** but not a particular city. **Never** high for origin-only (שיגורים מאיראן alone) — that is warning until a later line narrows scope."
    )
    # Mini models often confuse "מיקוד" + city name with "מיקוד למרכז" (high). Spell out the downgrade.
    PRIORITY_NAMED_CITY_FOCUS = (
        "Named-city focus vs generic corridor (CRITICAL — apply on every merge and on first qualification):\n"
        "- If the combined text **names a specific Israeli city** in גוש דן / המרכז (including **הרצליה**, רמת גן, פתח תקווה, בני ברק, תל אביב, רמת השרון, …) as the **מיקוד / focus / impact / arrival / אזעקה** of the threat, and **גבעתיים** is **not** named as affected — priority MUST be **informational**, NOT high.\n"
        "- Treat phrases like **המיקוד הרצליה**, **מיקוד בהרצליה**, **המיקוד: הרצליה**, **פגיעה/חדירה/הגעה בהרצליה** as **city-localized** scope → **informational**.\n"
        "- **High** is wrong when the only geographic precision is such a named city (Herzliya etc.). **Downgrade** high → informational when a new line narrows the incident from generic \"מרכז/גוש דן\" to **הרצליה** (or another listed informational city).\n"
        "- **Informational → high on salvo/continuation (CRITICAL):** **Never** raise **informational → high** **only** because of **שיגורים נוספים** / **מטח נוסף** / **זוהו שיגורים נוספים** — those lines do **not** by themselves place the **new** threat in the **priority corridor**. Do **not** assume additional launches share an earlier line's **למרכז** unless the same update **explicitly** ties this continuation to **generic** **המרכז/גוש דן/מיקוד למרכז/למרכז** (or names **גבעתיים**). **Upgrade to high** only when a **new** fact states that **this** continuation is aimed **generically** at the priority district — **המרכז**, **גוש דן**, **מיקוד למרכז**, **למרכז**, **מחוז המרכז**, Tel Aviv metro **as a region** — **without** narrowing **that** continuation to a single named non-Givatayim city. Examples: **שיגורים נוספים כעת למרכז** / **שיגורים נוספים — למרכז** → **high**; bare **שיגורים נוספים** with no new geographic aim → **stay informational**; **שיגורים נוספים — המיקוד הרצליה** → **informational**.\n"
        "- **Multi-beat vs duplicate geography (CRITICAL):** The narrative may already say **למרכז** / **המרכז** for the **first** salvo and also **המיקוד הרצליה** — **informational** for that beat. A **later** line **שיגורים נוספים** does **not** reset priority to **high** by itself (see previous bullet). **Do not** treat **מרכז** / **למרכז** / **גוש דן** as \"already said\" or as **NOT new content** when they **explicitly scope the additional launches** (including a **short reply** under **שיגורים נוספים**: **מרכז**, **למרכז**, **המרכז**). That continuation-aim is **new** even if \"מרכז\" appeared earlier for the **first** wave. **Only then** — when those **additional** launches are **explicitly** aimed **generically** at **המרכז/גוש דן/למרכז** — set **priority=high**; the **הרצליה** informational rule for an **earlier** beat does **not** block this upgrade.\n"
        "- **High** stays valid only while scope stays **generic** (למרכז, מיקוד למרכז, גוש דן, Tel Aviv metro **without** a more specific non-Givatayim city focus) **or** **גבעתיים** is explicitly included.\n"
    )
    GUIDELINES = (
        "Guidelines:\n"
        "- Rephrase the message in your own words; avoid verbatim text and repetition.\n"
        "- State ONLY facts present in the provided text. NEVER add, infer, or embellish.\n"
        "- Do not include safety recommendations (e.g. 'הישארו מעודכנים', 'הישארו בסמוך למרחב המוגן').\n"
        "- Do not include verification status (e.g. הפרטים בבדיקה).\n"
        "- Do not include details about explosions or impact (e.g. הנפילה, הפגיעה, הפיצוץ).\n"
    )
    DISQUALIFIERS = (
        "NOT qualified (set qualified=false, priority=none) when ANY of these apply:\n"
        "- News/wire report, journalist attribution (רויטרס, AP, כתב, דיווח), analyst or diplomatic commentary, political/legal/diplomatic news (court rulings, statements, sanctions), strategic threats framed as news.\n"
        '- Story coverage or documentation (e.g. "תיעוד").\n'
        '- Past event / recap: something that already happened or summarizes what already unfolded — "הנפילה", "במטח האחרון", past-tense explosions/impacts/interceptions, "הותר לפרסום" of a past impact, or time-window framing like "בשעה האחרונה" / "בשעות האחרונות" tallying facts already on the record (e.g. "יש יירוטים ונפילות", "לא דווח על נפגעים") without a concurrent live civil-defense instruction (חובת שהייה, אזעקה פעילה, מיקוד כעת, שיגורים בדרך) in the same message.\n'
        "- All-clear / safe to leave shelter (ניתן לצאת, סיום חובת שהייה במרחב מוגן).\n"
        '- Live-index header ("אזעקות כעת", "שיגורים כעת") without explicit instructions targeting the priority areas.\n'
        '- Threat explicitly limited to areas outside the priority areas (e.g. נגב, צפון, גולן, גליל, אילת, ירושלים, השפלה). This includes **explicit Israeli destination/aim** in those regions — e.g. **שיגורים מלבנון לצפון הארץ**, **לגליל**, **באזור הצפון** — even though the line also names a launch origin; origin does **not** override a clear out-of-scope destination. Refinements toward המרכז, מיקוד למרכז, למרכז, or מחוז המרכז are NOT "outside" — that is the same region as גבעתיים/גוש דן.\n'
        "- City hard override: the update names specific cities and NONE of them are priority area cities — set qualified=false, priority=none regardless of urgency wording.\n"
        "- Government statement such as a speech by the Prime Minister or Defense Minister.\n"
        '- Enemy/adversary FIRST-PERSON battle claim: a hostile entity (Iran/IRGC/משמרות המהפכה, Hamas, Hezbollah) speaking in its own voice — e.g. "תקפנו", "שיגרנו", "פגענו", "הפעלנו". This does NOT include third-party reports about launches originating from enemy territory (e.g. "שיגורים מאיראן", "טילים מלבנון") — those are operational alerts, not enemy claims.\n'
        "- Past-tense enemy announcements are news, not live civil-defense alerts.\n"
        '- Security/intelligence forecast: statements estimating or predicting future fire — e.g. "מעריכים כי", "הערכות", "צופים ש", "מקורות ביטחוניים". A prediction is NOT an active incoming threat.\n'
        '- Aggregate/editorial: situational roundups tallying alert zones (e.g. "כמעט N זירות", "עשרות אזעקות") with "בעקבות הירי/מטח/השיגורים" summary framing, or sensational openers (מטורף, וואו, שובר, בלעדי, דיווח) with aggregate/count content — qualified=false unless the same line also contains an immediate active threat to the priority areas (שיגורים בדרך, מיקוד, חובת שהייה, חדירה, אזעקה פעילה, ETA, arrival).\n'
        '- Never rely on aggregate counts or "בעקבות" situational wrap-ups as the main content.'
    )

    def get_first_prompt(self) -> str:
        return (
            f"You classify messages from Israeli Telegram channels about home-front security events.\n"
            f"{self.GUIDELINES}\n"
            f"Priority areas:\n {self.PRIORITY_AREAS}."
            "\n"
            "Set qualified=true when:\n"
            "- the message refers to an active missile, rocket, UAV, or other launch toward Israel, or preparations for one.\n"
            "- the line is a direct operational alert (incoming focus, מיקוד למרכז/לגוש דן, שיגורים בדרך, הכנה לשיגור)\n"
            "- Launch-origin statement (שיגורים מאיראן, שיגורים מלבנון, שיגורים מעזה, טילים מאיראן, etc.) — operational reporting about incoming fire, NOT an enemy battle claim — **qualified=true only if** the same message does **not** also satisfy the DISQUALIFIER that limits impact to areas outside the priority areas (see next bullet).\n"
            "- **DISQUALIFIERS win over launch-origin:** if the text already aims or limits the threat to **only** נגב/צפון/גליל/גולן/ירושלים/אילת/השפלה (or synonymous regional phrasing like לצפון הארץ), set qualified=false even when Lebanon/Iran/Gaza origin is mentioned.\n"
            "\n"
            "Priority on first qualification (CRITICAL): If the message qualifies only because of launch origin / generic incoming fire and does **not** in the same text name or aim the threat at גבעתיים, גוש דן, המרכז, מיקוד למרכז, or a city in that band — set **priority=warning**. Reserve **priority=high** for lines that already tie the threat to the priority areas in that message.\n"
            "\n"
            f"{self.PRIORITY_NAMED_CITY_FOCUS}\n"
            "\n"
            f"{self.DISQUALIFIERS}\n"
            f"{self.PRIORITY_SCALE}\n"
            f"- Reply with a single JSON object only - {self.FIRST_PROMPT_RESPONSE}\n"
        )

    def get_ongoing_prompt(self) -> str:
        related = (
            "related\n"
            "    true when the new message is part of the same operational incident (same salvo, scope refinement, shelter instructions, interception outcome).\n"
            "    Open-incident scope thread (CRITICAL): Set related=true when the new line refines the same live threat: clearer destination or region (including areas outside the priority areas), cities, ETA, arrival timing, siren timing, or scope narrowing. Do NOT set related=false only because a standalone opener would be disqualified for naming non-priority areas. Fold those facts into response_message; then use step 3-4 for ended/qualified.\n"
            '    Unrelated: Set related=false only when the new message is clearly a different story (news wire, past event, political commentary, foreign desk, aggregate situational roundup tallying many zones with summary framing without refining the same live salvo).\n'
            "    Note: Stating launch origin with ongoing home-front framing is operational reporting, not foreign news."
        )
        response_message = (
            "response_message\n"
            "    The full body text to display. The body has two parts:\n"
            "    PART A (narrative): a short Hebrew paragraph with all accumulated facts. This is provided to you already pre-built — do NOT remove or shorten it.\n"
            "    PART B (latest delta): exactly one line `{arrival_time} - {new fact}`, separated from PART A by one blank line."
            "\n"
            "    Algorithm for new messages (not source edits):\n"
            "    Step 1: Copy the existing update as-is — this becomes PART A. NEVER remove content from it.\n"
            "    Step 2: Check whether the incoming message adds a NEW fact not already present anywhere in PART A (see IS/NOT new content below). When deciding \"duplicate\": **do not** treat **מרכז/למרכז/גוש דן** as duplicate of an earlier line if the new text **scopes שיגורים נוספים** (or a reply under that message) — that is a **new** fact for the **continuation** salvo.\n"
            "    Step 3: If yes — append after a blank line: `{arrival_time} - {new fact in Hebrew}`.\n"
            "             If no — return PART A unchanged, set qualified=false, priority=none.\n"
            "\n"
            "    The result ALWAYS has: PART A (unchanged) + blank line + exactly one PART B line. Or PART A alone if nothing new.\n"
            "    NEVER output two or more `{time} - ...` lines. Every merge produces at most one.\n"
            "    NEVER drop, shorten, or rewrite PART A — it already contains all previously accumulated facts.\n"
            "\n"
            "    IS new content (append as PART B):\n"
            "    - A destination/corridor not yet in PART A (e.g. לאיזור המרכז when narrative only says origin).\n"
            "    - A specific city or neighborhood not yet named.\n"
            "    - An upcoming ETA or arrival time not yet mentioned (skip if already past).\n"
            "    - A launch origin not yet stated.\n"
            "    - A shelter / civil-defense instruction not yet present.\n"
            "    - An explicit scope refinement to a different area.\n"
            "    - Additional launches / salvo continuation (שיגורים נוספים, מטח נוסף) — **new content for the body**, but **do not** bump priority to **high** from **informational** unless the same line (or a tied reply) also states **generic** aim at **המרכז/גוש דן/למרכז** for **that** continuation (see Named-city focus).\n"
            "    - **Continuation destination:** **מרכז**, **למרכז**, **המרכז**, **גוש דן** (or a one-word reply with parent context pointing at **שיגורים נוספים**) — **always** new when it specifies where **those additional launches** are aimed, even if PART A already contains **למרכז** for an **earlier** salvo.\n"
            "    NOT new content (return PART A unchanged, set qualified=false, priority=none):\n"
            "    - Same fact already in PART A, just rephrased — **except** continuation-scope as in the bullet above.\n"
            "    - Echo / confirmation / restatement of existing content.\n"
            "\n"
            "    Delta source: PART B wording MUST reflect the **incoming message** (you may use parent/reply context **only** to decide **which salvo** a fragment scopes — e.g. a reply under **שיגורים נוספים** — not to invent facts).\n"
            "    When related=false: return the existing update text unchanged.\n"
            "    When ended=true: append `{arrival_time} - {closure summary in Hebrew}` as PART B.\n"
            "    Source edits (same message_id revised on Telegram): PART A is the narrative paragraph(s) above any `{HH:MM} -` lines; PART B is zero or one `{arrival_time} - {fact}` line.\n"
            "    If the edit only expands or corrects text for a fact that already has a `{HH:MM} - ...` line (same story beat — e.g. all-clear wording grows), REPLACE that single line in place with `{arrival_time} - {full post-edit fact in Hebrew}`. Do NOT add a second `{HH:MM} -` line below it — the body must never show two timestamp lines for one edited source.\n"
            "    If the edit introduces a genuinely new fact (not a rewrite of the last line), you may append one new PART B line using the arrival time provided in the prompt for this edit.\n"
            "    **Geographic edits on continuation lines:** Changing **מרכז** ↔ **למרכז** on a message that is **only** **שיגורים נוספים** (or its thread) **does** express **generic regional aim** for **those** additional launches — then **priority=high** per Informational → high; if the post-edit text is still **only** \"שיגורים נוספים\" with no **למרכז**/corridor, **do not** raise to **high**.\n"
            "\n"
        )
        ended = (
            "ended\n"
            "    true when: all-clear or safe to leave shelter; scope confirmed entirely outside priority areas; no remaining active danger.\n"
            '    Scope-close trigger (CRITICAL): Once the combined information establishes the threat targets ONLY areas outside the priority areas (e.g. only נגב/דרום, only צפון/חיפה, but NOT גבעתיים/גוש דן/המרכז), set ended=true and close_reason="out_of_subscriber_areas" IMMEDIATELY — even if the threat itself is still active.\n'
            '    Center / מרכז guard (CRITICAL): Any line that places the salvo toward המרכז, מיקוד למרכז, למרכז, מרכז הארץ, or Tel Aviv metro keeps the threat inside the priority areas — do NOT end with out_of_subscriber_areas.\n'
            "    Do NOT keep ended=false just because the overall event is still developing — once it is clear the threat will not affect the priority areas, end it.\n"
            '    close_reason: "all_clear" or "out_of_subscriber_areas" as appropriate. Null when ended=false.\n'
        )
        qualified = (
            "4 - qualified / priority\n"
            "    When ended=true: qualified=false, priority=none.\n"
            "    When related=false: ended=false, qualified=false, priority=none. Keep response_message as the existing update text unchanged.\n"
            "    Qualification lock: classify the **combined** situation after the merge. Re-run every DISQUALIFIERS check on that combined picture. "
            "If the narrative describes a threat whose scope is **only** outside the priority areas, qualified MUST be false and priority MUST be none.\n"
            "    Monotonicity for out-of-scope: if the existing update already established scope only outside the priority areas, a later message that adds no new facts placing the threat inside those areas MUST NOT increase priority and MUST keep qualified=false.\n"
            "    Priority refresh (CRITICAL): choose `priority` from the **merged** narrative only — do not copy the previous incident priority when the new facts change scope. When a line narrows focus to **הרצליה** (or another named non-Givatayim city), apply the Named-city focus rules and **downgrade** high → informational. **Upgrade** informational → **high** only when a **new** fact explicitly places **this** salvo/continuation toward **generic** **המרכז/גוש דן/מיקוד למרכז** (continuation-scope or same-line phrasing) — **not** on **שיגורים נוספים** alone, even if **המיקוד הרצליה** for an **earlier** beat stays in PART A.\n"
        )
        return (
            f"You manage an open Israeli home-front incident alert in the priority areas.\n"
            f"{self.GUIDELINES}\n"
            f"Priority areas: {self.PRIORITY_AREAS}.\n"
            "\n"
            "Do not treat trailing channel promos as downgrading priority if the operational line is unchanged.\n"
            "\n"
            "You will receive (in the user message):\n"
            "- The existing update (the narrative the user is currently seeing)\n"
            "- The existing incident priority\n"
            "- A new incoming message (with optional parent message context)\n"
            "- Optionally: authoritative source messages (ground-truth timeline)\n"
            "\n"
            "Your decisions:\n"
            f"1 - {related}\n"
            f"2 - {response_message}\n"
            f"3 - {ended}\n"
            f"4 - {qualified}\n"
            f"{self.DISQUALIFIERS}"
            "- If you have nothing new to add, return the existing update unchanged and set qualified=false and priority=none.\n"
            "\n"
            f"{self.PRIORITY_SCALE}\n"
            "\n"
            f"{self.PRIORITY_NAMED_CITY_FOCUS}\n"
            "\n"
            "Merge rules:\n"
            "    - For new messages: follow the algorithm in step 2 exactly. Result must never have more than one `{time} - ...` line per merge.\n"
            "    - For source edits: rebuild from authoritative source lines; keep at most one `{HH:MM} -` line for the message being edited — update it in place when the text grows; never stack duplicate times for the same closure.\n"
            "    - NEVER invent facts not present in either the existing update or the new message.\n"
            "    - Source edits: the post-edit authoritative source lines override earlier wording. If an edit replaces alert text with non-alert filler, strip that channel's contribution; rebuild from remaining sources only.\n"
            "\n"
            "subject: Hebrew headline (max 6 words) only when qualified=true AND priority=high AND existing incident priority was NOT already high. Empty string otherwise.\n"
            "\n"
            f"Reply with a single JSON object only - {self.ONGOING_PROMPT_RESPONSE}"
        )

    def get_reprocess_after_deletion_prompt(self) -> str:
        return (
            f"You manage an open Israeli home-front incident alert for a user in the priority areas.\n"
            f"Priority areas: {self.PRIORITY_AREAS}.\n"
            f"{self.GUIDELINES}\n"
            "One or more source messages were removed from Telegram (deleted). They must no longer influence the narrative.\n"
            "You will receive:"
            "- The existing update text the user is currently seeing (may be partially obsolete)"
            "- The existing incident priority"
            "- The remaining authoritative source messages only (ground truth)\n"
            "Rebuild the incident from scratch using ONLY the remaining source lines. Treat the existing update as a hint that may be wrong; the sources are authoritative.\n"
            f"{self.DISQUALIFIERS}\n"
            f"{self.PRIORITY_SCALE}\n"
            f"{self.PRIORITY_NAMED_CITY_FOCUS}\n"
            "Rules:\n"
            "    - response_message — One concise Hebrew narrative reflecting ONLY facts still present in the remaining sources.\n"
            "    - related — Always true (this is a correction pass, not a new thread).\n"
            "    - ended — true only if the remaining sources alone contain a real closure signal (all-clear, scope entirely outside priority areas). Otherwise false.\n"
            "    - When ended=true: qualified=false, priority=none, close_reason as appropriate.\n"
            "    - When ended=false: qualified=true if any remaining source supports an active incident, with priority from the combined remaining scope.\n"
            "subject: Hebrew headline (max 6 words) only when qualified=true AND priority=high AND the rebuilt incident warrants high priority. Empty string otherwise.\n"
            f"Reply with a single JSON object only - {self.ONGOING_PROMPT_RESPONSE}"
        )

    def get_closed_incident_subject_prompt(self) -> str:
        return (
            "A home-front incident alert has been closed. You receive the full Hebrew text shown to the user across all updates.\n"
            "Write one very short Hebrew sentence (max 12 words) summarizing the incident: geographic focus, what happened, and outcome. Do not invent facts. No emojis.\n"
            "\n"
            "Close reason: {close_reason_code}\n"
            "Close reason label: {close_reason_label}\n"
            f"Reply with a single JSON object only - {self.CLOSED_INCIDENT_SUBJECT_RESPONSE}"
        )

    def get_source_edit_addendum(self) -> str:
        return (
            "Source-edit rules for this turn:\n"
            "This message is an EDIT of a previously counted source. "
            "The authoritative source lines are the post-edit truth.\n"
            "- Rebuild response_message from authoritative sources. "
            "Drop facts that existed only in the pre-edit version and no longer appear.\n"
            "- Default to related=true unless the edit introduces a clearly separate event.\n"
            "- If the post-edit text is personal filler, apology, or channel noise with no "
            "operational civil-defense content, treat it like a removed alert line: keep "
            "qualified=false and priority=none; derive the narrative only from other sources; "
            "never re-qualify or raise priority from the old unified text alone.\n"
            "- After any source edit, re-apply DISQUALIFIERS to the combined scope. If the "
            "threat targets ONLY areas outside the priority areas, set qualified=false, "
            "priority=none, ended=true, and close_reason=\"out_of_subscriber_areas\" — same "
            "Scope-close trigger as in section 3 (ended). This applies even when the edit adds "
            "new operational facts that still lie entirely outside the priority areas; do NOT "
            "leave ended=false just because the edit is not a mere rephrase.\n"
            "- Keep ended=false only when the combined scope still plausibly affects priority "
            "areas, or when the edit is trivial origin/grammar with no new geographic scope "
            "and no all-clear (see Center / מרכז guard in section 3).\n"
            "- All-clear / safe to leave shelter: when the post-edit text clearly signals "
            "that, set ended=true with close_reason=\"all_clear\".\n"
            "- Timestamp line: if the unified text already ends with a `{HH:MM} - ...` line "
            "for this source and the edit only enriches that same closure, replace that "
            "line’s text (use the prompt’s arrival time for this edit as the prefix time). "
            "Do not append a second `{HH:MM} -` line with the same minute."
        )

    @staticmethod
    def _pre_absorb_timestamp_lines(text: str) -> str:
        import re
        if not text or "\n" not in text:
            return text
        parts = text.split("\n\n", 1)
        if len(parts) < 2:
            return text
        narrative = parts[0].strip()
        tail = parts[1].strip()
        if not tail:
            return narrative
        ts_re = re.compile(r"^\d{1,2}:\d{2}\s*-\s*(.+)$")
        absorbed = []
        leftover = []
        for line in tail.split("\n"):
            m = ts_re.match(line.strip())
            if m:
                fact = m.group(1).strip()
                if fact not in narrative:
                    absorbed.append(fact)
            elif line.strip():
                leftover.append(line)
        if absorbed:
            narrative = narrative.rstrip(".").rstrip()
            narrative += ", " + ", ".join(absorbed) + "."
        if leftover:
            return narrative + "\n\n" + "\n".join(leftover)
        return narrative

    def build_first_prompt(self, recent_closure_appendix: str | None = None) -> str:
        fp = self.get_first_prompt()
        if recent_closure_appendix:
            return f"{fp}\n\n{recent_closure_appendix}"
        return fp

    def build_ongoing_prompt(
        self,
        existing_update: str,
        existing_priority: str,
        source_messages_context: str | None = None,
        is_source_edit: bool = False,
        edited_message_previous_text: str | None = None,
        message_ts_il: str | None = None,
    ) -> str:
        op = self.get_ongoing_prompt()
        absorbed_update = (
            existing_update
            if is_source_edit
            else self._pre_absorb_timestamp_lines(existing_update)
        )
        parts: list[str] = [
            op,
            f"\nThe existing update: '{absorbed_update}'",
            f"The existing incident priority: '{existing_priority}'",
        ]
        if message_ts_il:
            if is_source_edit:
                parts.append(
                    f"Arrival time of this source edit (HH:MM, Israel): {message_ts_il}"
                )
            else:
                parts.append(f"Arrival time of the incoming message: {message_ts_il}")
        if source_messages_context and source_messages_context.strip():
            parts.append(
                f"\nAuthoritative source messages (latest versions only):\n"
                f"{source_messages_context.strip()}\n"
                f"Treat these as the ground-truth timeline."
            )
        if is_source_edit:
            parts.append(f"\n{self.get_source_edit_addendum()}")
            if edited_message_previous_text and edited_message_previous_text.strip():
                parts.append(
                    f"\nPrevious text of the edited source (now superseded):\n"
                    f"{edited_message_previous_text.strip()}"
                )
        return "\n".join(parts)

    def build_reprocess_after_deletion_prompt(
        self,
        existing_update: str,
        existing_priority: str,
        source_messages_context: str,
    ) -> str:
        rap = self.get_reprocess_after_deletion_prompt()
        parts: list[str] = [
            rap,
            f"\nThe existing update (may be partially obsolete): '{existing_update}'",
            f"The existing incident priority: '{existing_priority}'",
        ]
        if source_messages_context and source_messages_context.strip():
            parts.append(
                "\nRemaining authoritative source messages only:\n"
                f"{source_messages_context.strip()}\n"
            )
        else:
            parts.append("\nRemaining authoritative source messages: (none)")
        return "\n".join(parts)

    def build_closed_subject_prompt(
        self,
        close_reason_code: str,
        close_reason_label_text: str,
    ) -> str:
        return self.get_closed_incident_subject_prompt().format(
            close_reason_code=close_reason_code,
            close_reason_label=close_reason_label_text,
        )
