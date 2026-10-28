# Ruční porovnání Codex TUI: screen a tmux

Tento postup připravuje samostatný testovací projekt a registr. Nedotýká se
produkčních relací ani jejich konfigurace. **Agent jej nespouští.** Spuštění
skutečného interaktivního Codexu musí uživatel výslovně schválit; příkazy
`session start ... --approve-start` jsou lokální schválení konkrétního startu.
Nepoužívat skutečný rozpracovaný projekt ani soukromé konverzace. Test nic
nenahrává a nepotřebuje diagnostický dump prostředí, screenshot konverzace,
`script`, `capture-pane`, tmux `-v` ani screen logging.

## Předpoklady a příprava

V nové běžné KDE Konsole, mimo screen/tmux a mimo Codex, přejít do repozitáře.
Běžící původní GUI ponechat beze změny. Ověřit `screen -v`, `tmux -V` a
`codex --version`; pokud tmux není dostupný, nepokračovat k jeho startu.
Aplikace jej neinstaluje. Pro automatické testy byl tmux 3.5a rozbalen pouze
v `.tmp/tmux-test-runtime`, což není systémová instalace ani trvalá závislost.

Následující příkazy jsou po jednom řádku. Proměnné používat pouze v této nové
testovací Konsole; nepřepisují HOME ani uživatelský registr. `workspace bootstrap`
vytvoří vlastní volatilní `/tmp/$G2C_COMPARE_ID/{tmp,log}` pro nový projekt.

```sh
cd /home/peva/TEMP/mycode/gpt2codex
export G2C_COMPARE_BIN="$PWD/target/release/gpt2codex"
export G2C_COMPARE_GUI="$PWD/target/release/gpt2codex-gui"
export G2C_COMPARE_ROOT="$(readlink -f "$(mktemp -d "$PWD/.tmp/c-XXXXXXXX")")"
export G2C_COMPARE_ID="c${G2C_COMPARE_ROOT##*/c-}"
mkdir -m 700 -p "$G2C_COMPARE_ROOT/repos/tui" "$G2C_COMPARE_ROOT/repos/bridge" "$G2C_COMPARE_ROOT/c" "$G2C_COMPARE_ROOT/s" "$G2C_COMPARE_ROOT/screens"
export XDG_STATE_HOME="$G2C_COMPARE_ROOT/s"
export SCREENDIR="$G2C_COMPARE_ROOT/screens"
printf 'startup_message off\ndeflog off\n' > "$G2C_COMPARE_ROOT/screenrc"
export SCREENRC="$G2C_COMPARE_ROOT/screenrc"
export SYSSCREENRC=/dev/null
git init -q "$G2C_COMPARE_ROOT/repos/tui"
git init -q "$G2C_COMPARE_ROOT/repos/bridge"
"$G2C_COMPARE_BIN" workspace bootstrap --project-dir "$G2C_COMPARE_ROOT/repos" --id "$G2C_COMPARE_ID" --directory tui --git-name 'TUI Comparison' --git-email 'fixture@example.invalid' --config "$G2C_COMPARE_ROOT/c/config.toml"
printf '[project]\nid="gpt2codex"\ndirectory="bridge"\n' > "$G2C_COMPARE_ROOT/c/projects/gpt2codex.toml"
"$G2C_COMPARE_BIN" session projects --config "$G2C_COMPARE_ROOT/c/config.toml"
```

Pomocný registrovaný `gpt2codex` zde pouze poskytuje chybějící Bridge placeholder;
Bridge shell se v tomto registru nespouští. Cesta je záměrně krátká kvůli limitu
Unix socketu; aplikace příliš dlouhou cestu odmítne bez náhradního serveru.

## Stejné podmínky

V Konsole vybrat stejný výchozí profil, který GUI čte z Konsole: stejné písmo,
velikost, schéma barev a pozadí. GUI může backend přepnout v Nastavení; tím se
mění pouze klienti v **novém testovacím GUI**. Původní GUI neovládat. Jeho
nastavení není potřeba měnit. Poznamenat původní backend preference a po
porovnání ji v testovacím GUI vrátit, pokud byla změněna.

V každém klientovi nastavit pokud možno 90 sloupců × 28 řádků. Rozměr okna
v pixelech sám nezaručuje shodný počet buněk: backendy mají různé okraje a
scrollbar. Rozměry lze v testovacím shellu zjistit `stty size` před startem;
neposílat tento příkaz do TUI. Zaznamenat také font/pt, škálování/DPR,
přítomnost tapety, verzi Codexu/multiplexeru a počet současných klientů.
Používat stejné Codex nastavení/model a prázdnou testovací konverzaci.

Vnější TERM musí odpovídat skutečnému emulátoru. Nepřepisovat naslepo TERM
uvnitř multiplexeru; screen a tmux nastavují své terminálové schopnosti samy.
Zaznamenat pouze názvy TERM/COLORTERM, pokud jsou známé, nikoli celý environment
nebo TERMCAP. Nová tmux implementace zachovává locale pro Codex i attach;
locale C se používá jen pro metadata dotazy. Testovaný tmux běží s `-f /dev/null`
na samostatném socketu. Produkční GNU screen nadále respektuje dosavadní
screenrc; tento izolovaný postup záměrně používá vlastní screenrc bez logování.
Rozdíly v konfiguraci, vnitřním TERM, stavovém řádku a počtu buněk uvést ve
výsledku. Barvy ani ANSI podporu kvůli porovnání nevypínat.

## Postup porovnání po schválení startů

1. **Přímá Konsole:** spustit `codex` v testovacím projektu. Pozorovat prázdné
   TUI a resize na 100×32 a zpět. Tento testovací Codex potom běžně ukončit
   jeho vlastní akcí před dalším startem. Neovládat původní živý Codex.

```sh
cd "$G2C_COMPARE_ROOT/repos/tui"
codex
```

2. **Screen v Konsole:** samostatně schválit start v testovacím registru
   a připojit jej. Preference zůstává screen; explicitní volba dokládá záměr.
   Veškerý případný testovací vstup patří pouze tomuto prázdnému TUI.

```sh
"$G2C_COMPARE_BIN" session start --id "$G2C_COMPARE_ID" --multiplexer screen --task 'TUI comparison screen' --approve-start --config "$G2C_COMPARE_ROOT/c/config.toml"
"$G2C_COMPARE_BIN" session attach --id "$G2C_COMPARE_ID" --multiplexer screen --config "$G2C_COMPARE_ROOT/c/config.toml"
```

   Po pozorování odpojit **jen tento testovací klient** pomocí `Ctrl+A`, `D`.
   Screen a jeho testovací Codex mohou pokračovat pro další dvě zobrazení.
   Nevynucovat detach jiných klientů a nepoužívat `screen -d/-D/-X`.

3. **Tmux v Konsole:** nový slot vyžaduje druhé, samostatné schválení. Je
   jinou relací se stejnou verzí/prázdným TUI, nikoli migrací stejného procesu.

```sh
"$G2C_COMPARE_BIN" session start --id "$G2C_COMPARE_ID" --multiplexer tmux --task 'TUI comparison tmux' --approve-start --config "$G2C_COMPARE_ROOT/c/config.toml"
"$G2C_COMPARE_BIN" session attach --id "$G2C_COMPARE_ID" --multiplexer tmux --config "$G2C_COMPARE_ROOT/c/config.toml"
```

   Odpojit pouze tento testovací klient pomocí `Ctrl+B`, `D`.

4. **Vložené terminály:** z této Konsole spustit novou instanci sestaveného GUI
   s testovacím registrem. Otevřít Nastavení a nejprve vybrat Konsole KPart.
   Pozorovat zvlášť záložku `[screen]` a `[tmux]`, pak opakovat s QTermWidgetem.
   Porovnávat pokud možno s jediným připojeným klientem dané relace: druhou
   testovací záložku lze úmyslně odpojit přes menu Relace. Přepnutí backendu
   nepřipojí úmyslně odpojenou záložku; použít její tlačítko reconnect.

```sh
"$G2C_COMPARE_GUI" --bridge-cli "$G2C_COMPARE_BIN" --config "$G2C_COMPARE_ROOT/c/config.toml"
```

5. U každé kombinace zkusit resize tam a zpět, přepnutí záložek a znovupřipojení
   **testovacího klienta**. Zkratky vložení zkoušet pouze s neškodným textem
   v tomto testu, případně vůbec neposílat vstup a ověřit jen prázdné TUI.
   Pro samostatný test preference uložit tmux pro testovací projekt; oba sloty
   musí zůstat viditelné a připojitelné, bez dalšího startu. Totéž po návratu
   preference na screen. Restart již běžícího produkčního GUI není součástí testu.

## Výsledek a ukončení

Vyplnit následující tabulku jen nesoukromými pozorováními. Prázdný syntetický
ANSI test není důkazem, že původní Codex artefakty zmizely.

| Renderer | Multiplexer | Žluté pruhy | Resize tam/zpět | Buňky / klienti |
| --- | --- | --- | --- | --- |
| KDE Konsole | přímo | neověřeno | neověřeno | |
| KDE Konsole | screen | neověřeno | neověřeno | |
| KDE Konsole | tmux | neověřeno | neověřeno | |
| Konsole KPart | screen | neověřeno | neověřeno | |
| Konsole KPart | tmux | neověřeno | neověřeno | |
| QTermWidget | screen | neověřeno | neověřeno | |
| QTermWidget | tmux | neověřeno | neověřeno | |

Nejdříve uchovat pouze tuto tabulku a bezpečná metadata. Před případným úklidem
testovacích adresářů běžně ukončit pouze vlastní nově schválené testovací
Codexy, ověřit jejich status v testovacím registru a ukončit testovací GUI
přes Ukončit pouze GUI. Běžící session záznamy/sockety nemažte. Testovací
interrupted záznamy se samy nerecyklují; žádné `recover` nebo destruktivní
workaroundy nejsou pro porovnání potřeba. Produkční relace zůstávají nedotčené.

Po předání implementace vyčkat na výsledek uživatele pro oba backendy.
Ikony záložek, Attention Manager a další rozsáhlá diagnostika se neprovádějí.
