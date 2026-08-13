# What the READMEs will have to say — recorded, not written

Notes for whoever picks up `docs/readme-review` in the skill repo (and TCC's own README). **This
file changes no README.** It exists because the install flow moved a lot on 2026-08-13, during the
first from-scratch test on a second Mac, and the documentation still describes the old one.

Rule for every line below: it is written here in engineering terms and belongs in the README in
**one short, plain sentence for somebody who has never opened a terminal before**. If an item
cannot survive that compression, it does not belong in a README at all — it belongs in the FAQ or
in nothing.

Which README each item lands in is marked: **[skill]** = `README.md` + the three translations,
**[tcc]** = TCC's own README.

---

## Things that are now true and are not written down anywhere

**[skill] The install stops and asks for your Mac password.** Homebrew — which brings the Gemini
reviewer and `omp` — needs an administrator password and a RETURN, and it can only ask if a person
is sitting there. This is new: before 2026-08-13 that step silently failed for everyone using the
documented one-liner, so nobody ever saw the prompt. A reader who starts the install and walks
away will come back to a stalled terminal. Say so **before** the command, not after.

**[skill] The reviewer really does get installed now.** The README can stop hedging about setting
Gemini up by hand: the one-liner installs Antigravity (`agy`) and links it. What still has to be
done by hand, once, is signing it in with a Project ID from `aistudio.google.com/app/apikey`.

**[skill] `omp` is installed too.** One line: it is what lets the model picker offer anything that
is not Claude. Without it that dialog is empty.

**[skill] The "what to do next" list is now ordered and grouped**, and the README's own
step-by-step should match it rather than invent its own order: open a new terminal → `claude auth
login` → switch on REW's API → start. Everything else is "when you have time".

**[skill] You need a Claude login and nothing can do it for you.** Already true, already written,
but it is now also enforced on screen (TCC marks the picker when the Claude route has no login),
so the README and the app finally agree. Worth one sentence, not a paragraph.

**[tcc] The app has a name and an icon.** "Autosound TCC" in the Dock and the menu bar instead of
"python3.12", its own icon, and a shortcut on the Desktop. Only relevant to the README as a
screenshot: whatever picture is eventually taken now shows the real thing.

**[tcc] The first minute on a new project.** A brand-new project folder has no contract and no
context, so the reviewer answers "nothing to read yet — start the tune". That is the normal first
state, not a fault, and a reader who meets it before the README mentions it will file a bug.
Two sentences, in the getting-started part.

**[tcc] Where the logs are.** `~/Library/Logs/autosound-tcc/tcc.log`. It now also collects the
library warnings that used to print on launch, so "the terminal is quiet" is only true because
they went somewhere — say where, in the troubleshooting section.

## Things the READMEs must NOT say yet

**The GitHub backup is not offered by the installer.** Both rewritten READMEs recommend an account
for it; the installer does not ask, and nothing in the skill or TCC scripts it — the AI can do it
when it thinks of it, and that is all. Tracked as **SCR-049**. Until that lands, the READMEs may
recommend an account, but must not describe an offer that does not exist.

## Still open from the earlier README review

Unchanged by this session, repeated here so the list is in one place: **no screenshot** of the
window in TCC's README, and **the three translations (de/pl/uk) are out of sync** with the
rewritten English — mechanical to port, but it must happen before the merge or a non-English
reader gets the old version.

## And the gate itself

Merging `docs/readme-review` is the act of making 3.x the default for everyone arriving from a web
search, because the README leads new readers through `install.sh` and that script installs the
newest `v3.*` tag. It is gated on the clean-machine test finishing — which is the work that
produced this file, and which has not yet been run once end to end with everything in place.
