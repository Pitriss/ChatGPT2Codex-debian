# Tmux: ukončený program a explicitní archivace slotu

GNU screen a existující relace zůstávají beze změny. Tyto funkce jsou lokální
CLI operace, nejsou vystavené přes MCP a GUI nemá start/archive/respawn akci.
Původní `codex-test` se při testování ani nasazení těchto změn neupravuje.

## Nový start se zachováním panelu

```sh
./target/release/gpt2codex session start --id example --multiplexer tmux --remain-on-exit --approve-start --program-status
./target/release/gpt2codex session status --id example --multiplexer tmux --program-status
```

`--remain-on-exit` je volitelné pro konkrétní nový tmux start; bez něj zůstává
dosavadní chování. Není to globální nastavení ani změna existující relace.
Privátní startovací config nastaví remain-on-exit a detached politiku před
první instrukcí programu; nečte uživatelův tmux config. Potom se odstraní jen
tento vlastní pomocný config. Žádný automatický restart nebo navazující shell.

Server a program mají dva oddělené stavy. `state=attached|detached` znamená
ověřenou živou tmux session. `program=running|exited|unknown` se vztahuje na
původní panelový program (Codex/jeho launcher). Při `exited` je uveden exit code,
signál a čas, pokud je server poskytne. Signál může být číslo nebo standardní
název. GUI zobrazí „Proces: ukončen …; bez automatického restartu“ a dovolí
připojit původní zachovaný panel. Nezaměňuje ho za běžící Codex.

Programové údaje jsou ověřené proti uloženému pane ID a tmux identitě. Změněný
nebo chybějící panel je unknown, jiný panel se nepřebírá. Nečte se obsah panelu,
příkazová řádka ani prostředí. Exit údaje jsou dostupné, dokud žije server;
po zániku serveru se nevymýšlí ani zpětně nerekonstruují.

Nové GUI používá `session list --program-status`. Bez tohoto přepínače má
`session list/status/start` nadále původní výstup pro starší běžící GUI/CLI
konzumenty. Původní `screen` CLI má zachovaný formát a chování.

## Archivace skutečně přerušeného slotu

Nejdříve prohlédnout status a zkopírovat celé `session_id` a `generation`.
Archivační příkaz vyžaduje samostatný souhlas svázaný s touto identitou:

```sh
./target/release/gpt2codex session status --id example --multiplexer tmux --program-status
./target/release/gpt2codex session archive --id example --multiplexer tmux --expect-session-id DOPLNIT_CELE_ID --expect-process-start-ticks DOPLNIT_GENERATION --approve-archive
```

Úspěch vytvoří soukromý adresář `.archived-tmux-ID-PID-TICKS-CREATED` v původním
state directory. Obsahuje přesný originál `record.json`, samostatnou přesnou
kopii `record.snapshot.json`, číselná/identifikační `diagnostics.json` a původní
osiřelý `socket`, pokud existoval. Žádné existující důkazy se nepřepisují.
Originál se neupravuje a původní socket se nemaže, nýbrž přesune.

Kontroly před změnou stavu:

- Registrovaný projekt/root, vlastní bezpečný JSON, úplná tmux identita a přesná
  očekávaná identita/start ticks. Bridge slot a screen archivace jsou odmítnuty.
- Boot/PID namespace původního startu. Při stejném bootu je potřeba stejný PID
  namespace a prokázaná neexistence původního procesu; nečitelné procfs nestačí.
- Socket musí mít původní device/inode, správný typ/vlastníka/režim a potvrzený
  odmítnutý connect, nebo musí být prokazatelně nepřítomný. Živý listener,
  oprávnění/namespace chyby, symlink a změněná identita znamenají odmítnutí.
- Stav i původní obsah/inode JSON se před přesunem znovu zkontrolují pod zámkem.
  Přesuny používají Linux renameat2 s RENAME_NOREPLACE.

Nejdříve se zapíše a syncne kopie/diagnostika, potom se přesune osiřelý socket;
teprve nakonec originální JSON uvolní aktivní slot. Pád nebo chyba před tímto
posledním krokem ponechá slot rezervovaný. Částečný archiv se zachová pro
kontrolu, automaticky se nemaže ani nevrací. Opakovaný příkaz nemůže přepsat
existující archiv. Není to úplný sandbox proti souběžnému škodlivému procesu
se stejným UID; platí dosavadní lokální bezpečnostní model bridge.

Živý server se zachovaným mrtvým panelem není interrupted a archivace jej
odmítne. Archivace neukončuje relaci, nevolá tmux kill/respawn ani neposílá
terminálový vstup. Nový start vyžaduje další samostatné `--approve-start`.

## Kompatibilita a omezení

Staré konfigurace stále znamenají screen, původní preference jsou nezávislé
na skutečném multiplexeru slotu. Staré tmux JSON bez lifecycle údajů zůstávají
připojitelné stejnou kontrolou identity, jejich programový stav je unknown.
**Archivace starých/pending záznamů bez úplné identity a PID namespace původu
se odmítá.** Absence PID uvnitř sandboxu není důkazem zániku hostitelského
procesu. Automatická migrace/odhad namespace nebyly přidány; případný další
postup pro takový legacy slot vyžaduje zvláštní návrh a schválení.

## Izolované automatické a manuální ověření

Celý build/CTest a živé PTY regrese používají pouze nový fixture registr a
syntetický executable pojmenovaný codex, nikdy skutečný Codex nebo původní
`codex-test`. Žádné sdílené či výchozí uživatelské sockety:

```sh
cargo test --offline --all-targets
cargo build --release --offline
python3 ./gpt2codex-multiplexer-test.py --lifecycle --gui-build --backends
```

Helper potřebuje běžet s přístupem k lokálním PTY a v témže PID namespace jako
jeho vlastní servery. GUI helper je existující projektový build workflow,
ale jeho self-test má izolované HOME/config/state/SCREENDIR. Testovací úklid
smí uzavřít pouze identitou ověřený vlastní server s ukončeným syntetickým
programem. Nedotýká se běžících uživatelských relací.

Pro viditelné ruční ověření v samostatné testovací Konsole lze připravit nový
syntetický projekt následujícím postupem. Neprovádět v produkčním shellu ani
uvnitř rozpracovaného Codexu. Proměnné platí jen pro tento testovací shell:

```sh
cd /home/peva/TEMP/mycode/gpt2codex
export G2C_LIFE_BIN="$PWD/target/release/gpt2codex"
export G2C_LIFE_GUI="$PWD/target/release/gpt2codex-gui"
export G2C_LIFE_ROOT="$(readlink -f "$(mktemp -d "$PWD/.tmp/l-XXXXXXXX")")"
export G2C_LIFE_ID="l$(printf '%s' "${G2C_LIFE_ROOT##*/l-}" | tr '[:upper:]' '[:lower:]')"
mkdir -m 700 -p "$G2C_LIFE_ROOT/repos/test" "$G2C_LIFE_ROOT/repos/bridge" "$G2C_LIFE_ROOT/bin" "$G2C_LIFE_ROOT/c" "$G2C_LIFE_ROOT/s" "$G2C_LIFE_ROOT/screens"
export XDG_STATE_HOME="$G2C_LIFE_ROOT/s"
export XDG_CONFIG_HOME="$G2C_LIFE_ROOT/c"
export SCREENDIR="$G2C_LIFE_ROOT/screens"
export SCREENRC=/dev/null
export SYSSCREENRC=/dev/null
git init -q "$G2C_LIFE_ROOT/repos/test"
git init -q "$G2C_LIFE_ROOT/repos/bridge"
printf '#!/bin/sh\nprintf "\\033[33mSynthetic lifecycle test\\033[0m\\n"\nwhile [ ! -f "$G2C_LIFE_ROOT/finish" ]; do /bin/sleep 1; done\nexit 23\n' > "$G2C_LIFE_ROOT/bin/codex"
chmod 700 "$G2C_LIFE_ROOT/bin/codex"
export PATH="$G2C_LIFE_ROOT/bin:$PATH"
"$G2C_LIFE_BIN" workspace bootstrap --project-dir "$G2C_LIFE_ROOT/repos" --id "$G2C_LIFE_ID" --directory test --git-name 'Lifecycle fixture' --git-email 'fixture@example.invalid' --config "$G2C_LIFE_ROOT/c/config.toml"
printf '[project]\nid="gpt2codex"\ndirectory="bridge"\n' > "$G2C_LIFE_ROOT/c/projects/gpt2codex.toml"
"$G2C_LIFE_BIN" session start --id "$G2C_LIFE_ID" --multiplexer tmux --remain-on-exit --approve-start --program-status --config "$G2C_LIFE_ROOT/c/config.toml"
"$G2C_LIFE_GUI" --bridge-cli "$G2C_LIFE_BIN" --config "$G2C_LIFE_ROOT/c/config.toml" &
```

V testovacím GUI ověřit „Proces: běží“, odpojení/reconnect a přepnutí obou
backendů. V druhém shellu nastavit finish značku do přesně vypsané nové fixture
cesty (ne do původního codex-test). Program skončí s 23, GUI musí zachovat
panel a zobrazit ukončení bez opakovaného startu. Případně GUI dát na pozadí
pomocí vlastního desktopu a značku vytvořit ze stejné testovací Konsole:

```sh
touch "${G2C_LIFE_ROOT:?}/finish"
"$G2C_LIFE_BIN" session status --id "$G2C_LIFE_ID" --multiplexer tmux --program-status --config "$G2C_LIFE_ROOT/c/config.toml"
```

Archivaci při živém serveru s mrtvým panelem musí bridge odmítnout. Pro scénář
skutečného interrupted stavu lze postup zopakovat s další novou fixture bez
`--remain-on-exit`; po značce finish server sám skončí. Ze statusu zkopírovat
její celé ID/generation a explicitně schválit archive příkaz s týmž config a
state prostředím. Ověřit obsah archivu, `not_registered` a absenci dalšího
procesu. Teprve další samostatný schválený start smí vytvořit novou identitu.

Původní zachovaný testovací dead-pane server zůstává záměrně živý; případný
úklid vlastních nových testovacích relací musí být cílený a ručně schválený.
Adresáře/registry/sockety nemažte, dokud některý jejich server žije.
