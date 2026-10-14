"""Codex's own lines: install, sign-in, their progress and results, and the launch blockers that
name them (W-10 tcc#181 task 9). Four languages side by side per key; uk and en by the builder,
pl and de through the Advisor (2026-10-14). Plain data that imports nothing; `codex_terminal`
names `codexInstall`'s English in a terminal, which has no i18n (a test holds the two equal).
"""

STRINGS: dict[str, dict[str, str]] = {
    'codexInstall': {
        'en': 'Install Codex',
        'uk': 'Встановити Codex',
        'pl': 'Zainstaluj Codex',
        'de': 'Codex installieren',
    },
    'codexInstallTip': {
        'en': "Downloads OpenAI's own Codex (the official package, about 130 MB) into TCC's own"
              ' folder. Nothing else on the computer changes, and no administrator rights are '
              'needed. A Codex already installed is used instead, so this is offered only when '
              'there is none or it is too old.',
        'uk': 'Завантажує Codex від самої OpenAI (офіційний пакет, близько 130 МБ) у власну '
              'теку TCC. Більше нічого на компʼютері не змінюється, права адміністратора не '
              'потрібні. Уже встановлений Codex використовується замість нього, тож це '
              'пропонується, лише коли Codex немає або він застарий.',
        'pl': 'Pobiera Codex od samego OpenAI (oficjalny pakiet, około 130 MB) do własnego '
              'folderu TCC. Nic innego na komputerze się nie zmienia i nie są potrzebne '
              'uprawnienia administratora. Już zainstalowany Codex jest używany zamiast tego, '
              'więc ta opcja jest oferowana tylko wtedy, gdy go nie ma lub jest za stary.',
        'de': 'Lädt OpenAIs eigenen Codex (das offizielle Paket, rund 130 MB) in TCCs eigenen '
              'Ordner herunter. Am Computer wird sonst nichts geändert und es sind keine '
              'Administratorrechte erforderlich. Ein bereits installierter Codex wird '
              'stattdessen verwendet; dies wird daher nur angeboten, wenn keiner vorhanden oder'
              ' er zu alt ist.',
    },
    'codexSignIn': {
        'en': 'Sign in to Codex',
        'uk': 'Увійти в Codex',
        'pl': 'Zaloguj się do Codex',
        'de': 'Bei Codex anmelden',
    },
    'codexSignInTip': {
        'en': 'Opens the browser to sign in to Codex with your own ChatGPT account. Codex keeps'
              ' the login; TCC never sees the password.',
        'uk': 'Відкриває браузер, щоб увійти в Codex своїм обліковим записом ChatGPT. Вхід '
              'зберігає Codex; пароля TCC не бачить.',
        'pl': 'Otwiera przeglądarkę, aby zalogować się do Codex własnym kontem ChatGPT. '
              'Logowanie zachowuje Codex; TCC nigdy nie widzi hasła.',
        'de': 'Öffnet den Browser, um dich mit deinem eigenen ChatGPT-Konto bei Codex '
              'anzumelden. Codex speichert die Anmeldung; TCC sieht das Passwort nie.',
    },
    'codexCancel': {
        'en': 'Cancel',
        'uk': 'Скасувати',
        'pl': 'Anuluj',
        'de': 'Abbrechen',
    },
    'codexInstalling': {
        'en': 'Installing Codex… {percent}% ({done} of {total} MB)',
        'uk': 'Встановлюю Codex… {percent}% ({done} з {total} МБ)',
        'pl': 'Instalowanie Codex… {percent}% ({done} z {total} MB)',
        'de': 'Codex wird installiert… {percent}% ({done} von {total} MB)',
    },
    'codexInstalled': {
        'en': 'Codex is installed. Next: ⚙ Settings → Sign in to Codex.',
        'uk': 'Codex встановлено. Далі: ⚙ Налаштування → Увійти в Codex.',
        'pl': 'Codex został zainstalowany. Dalej: ⚙ Ustawienia → Zaloguj się do Codex.',
        'de': 'Codex ist installiert. Weiter: ⚙ Einstellungen → Bei Codex anmelden.',
    },
    'codexInstallUnsupported': {
        'en': 'TCC installs Codex on macOS and Windows only. Install it yourself: {url}',
        'uk': 'TCC встановлює Codex лише на macOS і Windows. Встановіть його самі: {url}',
        'pl': 'TCC instaluje Codex tylko na macOS i Windows. Zainstaluj go samodzielnie: {url}',
        'de': 'TCC installiert Codex nur unter macOS und Windows. Installiere es selbst: {url}',
    },
    'codexInstallNetwork': {
        'en': 'Codex could not be downloaded: {error}. Nothing was installed; try again when '
              'the connection is back.',
        'uk': 'Codex не вдалося завантажити: {error}. Нічого не встановлено; спробуйте ще раз, '
              'коли зʼєднання повернеться.',
        'pl': 'Nie udało się pobrać Codex: {error}. Nic nie zostało zainstalowane; spróbuj '
              'ponownie, gdy wróci połączenie.',
        'de': 'Codex konnte nicht heruntergeladen werden: {error}. Es wurde nichts installiert;'
              ' versuche es erneut, sobald die Verbindung wiederhergestellt ist.',
    },
    'codexInstallMismatch': {
        'en': 'The downloaded Codex is not the file TCC expects (its checksum differs), so it '
              'was not installed and nothing was left behind.',
        'uk': 'Завантажений Codex — не той файл, на який розраховує TCC (контрольна сума інша),'
              ' тож його не встановлено й нічого не залишено.',
        'pl': 'Pobrany Codex to nie ten plik, którego oczekuje TCC (suma kontrolna się różni), '
              'więc nie został zainstalowany i nic po nim nie zostało.',
        'de': 'Der heruntergeladene Codex ist nicht die Datei, die TCC erwartet (die Prüfsumme '
              'weicht ab), daher wurde er nicht installiert und es blieb nichts zurück.',
    },
    'codexInstallBadWheel': {
        'en': 'The Codex package could not be unpacked safely ({error}); nothing was installed.',
        'uk': 'Пакет Codex не вдалося безпечно розпакувати ({error}); нічого не встановлено.',
        'pl': 'Nie udało się bezpiecznie rozpakować pakietu Codex ({error}); nic nie zostało '
              'zainstalowane.',
        'de': 'Das Codex-Paket konnte nicht sicher entpackt werden ({error}); es wurde nichts '
              'installiert.',
    },
    'codexInstallDisk': {
        'en': 'Codex could not be written to the disk: {error}. Nothing was installed.',
        'uk': 'Codex не вдалося записати на диск: {error}. Нічого не встановлено.',
        'pl': 'Nie udało się zapisać Codex na dysku: {error}. Nic nie zostało zainstalowane.',
        'de': 'Codex konnte nicht auf die Festplatte geschrieben werden: {error}. Es wurde '
              'nichts installiert.',
    },
    'codexInstallCancelled': {
        'en': 'Codex installation cancelled; nothing was left behind.',
        'uk': 'Встановлення Codex скасовано; нічого не залишено.',
        'pl': 'Instalacja Codex została anulowana; nic po niej nie zostało.',
        'de': 'Codex-Installation abgebrochen; es blieb nichts zurück.',
    },
    'codexInstallWrongVersion': {
        'en': 'The unpacked Codex says it is {version}, not {pin}, so it was removed again.',
        'uk': 'Розпакований Codex каже, що він {version}, а не {pin}, тож його знову прибрано.',
        'pl': 'Rozpakowany Codex zgłasza wersję {version}, a nie {pin}, więc został ponownie '
              'usunięty.',
        'de': 'Der entpackte Codex meldet {version} statt {pin} und wurde daher wieder '
              'entfernt.',
    },
    'codexFinishInBrowser': {
        'en': 'Finish signing in to Codex in the browser.',
        'uk': 'Завершіть вхід у Codex у браузері.',
        'pl': 'Dokończ logowanie do Codex w przeglądarce.',
        'de': 'Schließe die Anmeldung bei Codex im Browser ab.',
    },
    'codexSignedIn': {
        'en': 'Signed in to Codex.',
        'uk': 'Вхід у Codex виконано.',
        'pl': 'Zalogowano do Codex.',
        'de': 'Bei Codex angemeldet.',
    },
    'codexSignInFailed': {
        'en': 'Sign-in to Codex did not finish: {error}',
        'uk': 'Вхід у Codex не завершився: {error}',
        'pl': 'Logowanie do Codex nie zostało zakończone: {error}',
        'de': 'Anmeldung bei Codex wurde nicht abgeschlossen: {error}',
    },
    'codexSignInCancelled': {
        'en': 'Sign-in to Codex cancelled.',
        'uk': 'Вхід у Codex скасовано.',
        'pl': 'Logowanie do Codex zostało anulowane.',
        'de': 'Anmeldung bei Codex abgebrochen.',
    },
    'codexMissing': {
        'en': '⚠️ Codex is not installed — ☰ → ⚙ Settings → Install Codex, or pick a Claude '
              'model.',
        'uk': '⚠️ Codex не встановлено — ☰ → ⚙ Налаштування → Встановити Codex, або обери '
              'модель Claude.',
        'pl': '⚠️ Codex nie jest zainstalowany — ☰ → ⚙ Ustawienia → Zainstaluj Codex, albo '
              'wybierz model Claude.',
        'de': '⚠️ Codex ist nicht installiert — ☰ → ⚙ Einstellungen → Codex installieren, oder '
              'wähle ein Claude-Modell.',
    },
    'codexTooOld': {
        'en': '⚠️ Codex {version} is older than {min}, the oldest TCC works with — ☰ → ⚙ '
              "Settings → Install Codex puts TCC's own copy beside it.",
        'uk': '⚠️ Codex {version} старіший за {min}, найстаріший, з яким працює TCC, — ☰ → ⚙ '
              'Налаштування → Встановити Codex поставить поруч власну копію TCC.',
        'pl': '⚠️ Codex {version} jest starszy niż {min}, najstarsza wersja, z którą działa TCC'
              ' — ☰ → ⚙ Ustawienia → Zainstaluj Codex umieści obok własną kopię TCC.',
        'de': '⚠️ Codex {version} ist älter als {min}, die älteste Version, mit der TCC '
              'funktioniert — ☰ → ⚙ Einstellungen → Codex installieren richtet eine eigene '
              'TCC-Kopie daneben ein.',
    },
    'codexSignedOut': {
        'en': '⚠️ Codex is not signed in — ☰ → ⚙ Settings → Sign in to Codex.',
        'uk': '⚠️ Codex не має входу — ☰ → ⚙ Налаштування → Увійти в Codex.',
        'pl': '⚠️ Codex nie jest zalogowany — ☰ → ⚙ Ustawienia → Zaloguj się do Codex.',
        'de': '⚠️ Codex ist nicht angemeldet — ☰ → ⚙ Einstellungen → Bei Codex anmelden.',
    },
    'codexTerminalHint': {
        'en': "To start Codex with TCC's tools: {command}",
        'uk': 'Щоб запустити Codex з інструментами TCC: {command}',
        'pl': 'Aby uruchomić Codex z narzędziami TCC: {command}',
        'de': 'Um Codex mit den Werkzeugen von TCC zu starten: {command}',
    },
}
