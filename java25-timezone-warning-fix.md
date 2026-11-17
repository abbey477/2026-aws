# Fixing "three-letter time zone ID is deprecated" warnings (Java 25+)

## Symptom

At startup, a Java app prints a burst of lines like:

```
WARNING: Use of the three-letter time zone ID "ACT" is deprecated and it will be removed in a future release
WARNING: Use of the three-letter time zone ID "AET" is deprecated and it will be removed in a future release
...
WARNING: Use of the three-letter time zone ID "VST" is deprecated and it will be removed in a future release
```

## Cause

- From **Java 25** on, the JDK logs this warning every time `TimeZone.getTimeZone(...)` is called with one of the old JDK 1.1 three-letter IDs (`CST`, `PST`, `EST`, `IST`, ...). See OpenJDK change **JDK-8342550**.
- When the **whole list** prints (ACT → VST), some code is looping over every time zone name and looking each one up. That code is almost always in a **library**, not in your app.
- The warning is **harmless**. The app still works. It's noise in the logs, and it's an early notice that these IDs will be removed in a future Java release.

### Common culprits

| Library | Why | Fix |
|---|---|---|
| **log4j-core 2.x (older, e.g. 2.17.1)** | Contains its own copy of `FastDateParser`. When a log date pattern contains a time zone letter (`z` / `zzz` / `Z`), it walks all zone names. | Remove `z`/`Z` from the `%d{...}` pattern, and/or upgrade log4j |
| **commons-lang3 < 3.18.0** (often pulled in transitively) | `FastDateParser` has the same behaviour | Pin commons-lang3 to 3.18.0 or later (I believe 3.18.0 fixed this, but haven't confirmed the version) |
| **joda-time (old, e.g. 2.1)** | Reads zone names. A less likely cause, but very old | Upgrade to the latest 2.x |
| **JVM / OS settings** | `-Duser.timezone=CST`, `TZ=CST`, etc. | Use region IDs, e.g. `America/Chicago` |
| **Your own code** | `TimeZone.getTimeZone("EST")` etc. | Use region IDs (see the mapping in `ZoneId.SHORT_IDS`) |

---

## Step 1: Find which jar is responsible (per project)

### Quick scan of a lib folder

Run this from the folder holding the app's jars. It lists every jar whose classes contain code that walks the zone names:

```bash
for j in *.jar; do
  if unzip -p "$j" '*.class' 2>/dev/null | grep -aqE 'getZoneStrings|getAvailableIDs'; then
    echo "$j"
  fi
done
```

### Scan several projects at once

```bash
# Edit the paths to point at each project's lib folder
for dir in /path/to/projectA/lib /path/to/projectB/lib /path/to/projectC/lib; do
  echo "== $dir"
  for j in "$dir"/*.jar; do
    if unzip -p "$j" '*.class' 2>/dev/null | grep -aqE 'getZoneStrings|getAvailableIDs'; then
      echo "   $(basename "$j")"
    fi
  done
done
```

### What the scan tells you, and what it doesn't

- **No match = very likely innocent.** A jar that doesn't match almost certainly never calls those two methods directly. Ruling jars out is the reliable part.
- **A match ≠ proof.** It means the code *exists* in the jar, not that it *runs*. For example, log4j only reaches that code when a date pattern has a time zone letter.
- **Blind spots:**
  - Code that triggers the warning another way (e.g. its own hard-coded ID list, or `ZoneId.SHORT_IDS` + `TimeZone.getTimeZone`).
  - Jars nested inside other jars (Spring Boot fat jars: `BOOT-INF/lib`), and jars outside the scanned folder.
  - Rare false positives, since this is a raw byte search.

### Check the log4j config for time zone letters

```bash
# Config outside the jar
grep -rnE '%d(ate)?\{[^}]*[zZ]' /path/to/config/

# Config packaged inside the app jar
unzip -p yourapp.jar 'log4j2*' | grep -nE '%d(ate)?\{[^}]*[zZ]'
```

### Check for commons-lang3 coming in transitively (Maven)

```bash
mvn dependency:tree -Dincludes=org.apache.commons:commons-lang3
```

### Definitive: catch the actual caller with a stack trace

1. Start the app with the debug agent (it will wait for the debugger):
   ```bash
   java -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005 ...your usual args...
   ```
2. In another terminal:
   ```bash
   jdb -attach 5005
   > stop in java.util.TimeZone.getTimeZone(java.lang.String)
   > cont
   ```
3. When it stops, `print ID` shows the ID being looked up. Type `cont` until it's a three-letter one (e.g. `"ACT"`), then type `where`. The stack trace shows exactly which library made the call.

---

## Step 2: Apply the fix

Do these in order. Stop when the warnings are gone.

### 2a. Change the log4j date pattern (quickest, config only)

Remove `z` / `zzz` / `Z` from inside `%d{...}`:

```xml
<!-- before -->
<PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSS z} %-5p %c - %m%n"/>

<!-- after -->
<PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSS} %-5p %c - %m%n"/>
```

If you still want the time zone in the logs, set it as an **option**, not a pattern letter:

```xml
<PatternLayout pattern="%d{yyyy-MM-dd HH:mm:ss.SSS}{America/Chicago} %-5p %c - %m%n"/>
```

Rerun the app. If the warnings stop, you've confirmed log4j was the cause and fixed it.

### 2b. Upgrade the old libraries (lasting fix)

```xml
<properties>
    <!-- keep log4j-api, log4j-core, log4j-slf4j-impl on the SAME version -->
    <log4j.version>2.25.2</log4j.version>   <!-- or the latest 2.25.x in your repo -->
</properties>

<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-core</artifactId>
    <version>${log4j.version}</version>
</dependency>
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-api</artifactId>
    <version>${log4j.version}</version>
</dependency>
<dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-slf4j-impl</artifactId>
    <version>${log4j.version}</version>
</dependency>

<dependency>
    <groupId>joda-time</groupId>
    <artifactId>joda-time</artifactId>
    <version>2.14.0</version>   <!-- or the latest 2.x -->
</dependency>

<!-- Only if commons-lang3 shows up in dependency:tree below 3.18.0 -->
<dependency>
    <groupId>org.apache.commons</groupId>
    <artifactId>commons-lang3</artifactId>
    <version>3.18.0</version>
</dependency>
```

Notes:
- I believe newer log4j 2.25.x moved date formatting to `java.time`, which shouldn't trigger the warning, but I haven't confirmed that. Verify after upgrading.
- Check your internal Maven repository for the newest versions you're allowed to use.

### 2c. Fix any JVM/OS settings and your own code

- Replace `-Duser.timezone=CST` / `TZ=CST` with region IDs like `America/Chicago`.
- Replace `TimeZone.getTimeZone("EST")` and similar with region IDs, e.g. `"America/New_York"`. `ZoneId.SHORT_IDS` has the full mapping.

### 2d. Last resort: hide the warning

Use this when the cause is in a jar you don't own (e.g. an internal shared library) and you're waiting for its owners to fix it.

**Option 1: JUL logging config**

```properties
# logging.properties
java.util.TimeZone.level = SEVERE
```

```bash
java -Djava.util.logging.config.file=/path/to/logging.properties ...
```

> I haven't confirmed that the logger is named `java.util.TimeZone`. If this has no effect, use Option 2.

**Option 2: filter the output**

```bash
java ... 2> >(grep -v "three-letter time zone" >&2)
```

**Option 3:** run that app on Java 21 until the library is fixed.

---

## Checklist for each affected project

- [ ] Confirm the app runs on Java 25+ (`java -version`)
- [ ] Run the jar scan on the project's lib folder
- [ ] Grep the log4j config for `z`/`Z` in `%d{...}`
- [ ] Remove the time zone letter from the pattern (or move the zone to the `{...}` option) and rerun
- [ ] Upgrade log4j (all artifacts together) and joda-time; pin commons-lang3 if it's old
- [ ] Check `-Duser.timezone` / `TZ` and the code for three-letter IDs
- [ ] Still there? Get a `jdb` stack trace and raise it with the owning team; hide the warning meanwhile
