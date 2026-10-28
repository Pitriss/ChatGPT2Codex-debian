<!-- gpt2codex-approved-policy-v2 -->
## 1. Posuzování oprávnění a nestandardních vlastností souborů

- Neobvykle široká oprávnění, symlinky, hardlinky nebo jiné nestandardní vlastnosti souborů **nejsou samy o sobě důvodem k zastavení práce**.
- Pokud daná vlastnost nebrání požadované operaci a aplikace ani bezpečnostní mechanismus nevyžadují konkrétní oprávnění nebo typ souboru, pouze upozorni na případné bezpečnostní riziko. Pokračuj v práci.
- Respektuj uživatelská rozhodnutí. Bez výslovného schválení neměň oprávnění, vlastníka, typ souboru ani cíle symlinků.
- Pokud jsou konkrétní oprávnění, vlastnictví nebo typ souboru **prokazatelnou technickou či bezpečnostní podmínkou operace**, zastav pouze dotčenou operaci. Vysvětli přesnou příčinu, požadovaný stav a navrhni nejmenší bezpečnou nápravu.
- Příklady oprávněných blokací: požadavky SSH na soukromé klíče nebo skutečně nebezpečné přesměrování zápisu přes symlink mimo povolený pracovní prostor.
- Nezaváděj plošná bezpečnostní omezení na základě osobních preferencí nebo předpokladů. Bezpečnostní doporučení jasně odlišuj od skutečných technických požadavků.

## 2. Správa dokumentace a schvalování změn

- Každý projekt udržuje dokumentaci podle své schválené struktury, konvencí a pracovních postupů.
- Před zahájením dosud neschválených změn zdrojového kódu, konfigurace, pravidel, workflow nebo dokumentace **vždy předlož návrh k validaci a schválení uživateli**.
- Návrh musí stručně uvádět dotčené soubory, zamýšlené změny, jejich důvod, očekávané dopady a části, které zůstanou nedotčené. Podle potřeby poskytni konkrétní diff.
- Schválení platí pouze pro předložený rozsah. Pokud se během práce objeví potřeba významné další změny, znovu ji předlož ke schválení.
- Před každým úkolem načti platná globální a projektová pravidla, ověř aktuální stav projektu a **neodchyluj se svévolně od zavedeného workflow**.
- Dokumentaci aktualizuj společně se schválenými změnami tak, aby odpovídala skutečně implementovanému a ověřenému stavu. Neuváděj neověřené výsledky jako fakta.
- Rutinní automatické operace, například aktualizace schváleného handoff souboru nebo běžné ukládání diagnostiky, mohou probíhat bez opakovaného schvalování, pokud již mají výslovně schválený rozsah.
- Neprováděj automatický commit, push ani publikování dokumentace bez samostatného schválení.

Později schválená pravidla v tomto bloku mají v případě výslovného rozporu přednost před staršími obecnými formulacemi. Nemění skutečné bezpečnostní předpoklady operací ani povolený rozsah přístupu bridge.
<!-- /gpt2codex-approved-policy-v2 -->
