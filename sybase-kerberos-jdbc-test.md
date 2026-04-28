# Sybase + Kerberos + JDBC on Java 17 — Test Guide

A minimal guide to testing a Sybase database connection using Kerberos authentication via JDBC on Java 17.

---

## Prerequisites

Before starting, confirm the following:

- ✅ Path to your `krb5.conf` is known
- ✅ jConnect driver `jconn4.jar` is available (version 16.0 SP04 or newer)
- ✅ Java 17 installed
- ✅ Sybase service principal name is known (ask your DBA/SRE if unsure)

### Pre-flight check with klist (optional but recommended)

Run `klist` once before starting to confirm Kerberos is set up correctly. The output is **not** used by the Java code — Java reads the ticket cache directly from disk. This is just a sanity check.

```bash
klist          # confirms a valid TGT exists and hasn't expired
klist -e       # confirms encryption is AES, not DES or RC4
```

If both look good, move on. You only need to revisit `klist` if the Java test fails — it helps narrow down whether the issue is at the Kerberos layer or the Java/JDBC layer.

---

## Step 1: Create the JAAS Config File

Save this as `jaas.conf` (anywhere convenient — e.g., next to your `krb5.conf`):

```
SybaseJDBC {
    com.sun.security.auth.module.Krb5LoginModule required
    useTicketCache=true
    doNotPrompt=true;
};
```

**What this does:**
- `SybaseJDBC` — a name you choose (referenced internally)
- `Krb5LoginModule` — Java's built-in Kerberos auth module
- `useTicketCache=true` — uses the existing ticket from `kinit`
- `doNotPrompt=true` — fails fast if no ticket is found (no password prompts)

---

## Step 2: Java Test Class

Create `SybaseKerberosTest.java`:

```java
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

public class SybaseKerberosTest {

    public static void main(String[] args) throws Exception {

        String url = "jdbc:sybase:Tds:HOST:PORT/DATABASE"
                   + "?REQUEST_KERBEROS_SESSION=true"
                   + "&SERVICE_PRINCIPAL_NAME=sybase/HOST@REALM";

        System.out.println("Connecting...");

        try (Connection conn = DriverManager.getConnection(url);
             Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery("SELECT 1")) {

            if (rs.next()) {
                System.out.println("SUCCESS! Result: " + rs.getInt(1));
            }
        }
    }
}
```

### Replace these 4 placeholders

| Placeholder | Example |
|---|---|
| `HOST` | `sybase01.corp.example.com` |
| `PORT` | `5000` |
| `DATABASE` | `mydb` |
| `sybase/HOST@REALM` | `sybase/sybase01.corp.example.com@EXAMPLE.COM` |

---

## Step 3: Compile and Run

### Compile

```bash
javac -cp jconn4.jar SybaseKerberosTest.java
```

### Run (Linux/Mac)

```bash
java -cp .:jconn4.jar \
     -Djava.security.krb5.conf=/path/to/krb5.conf \
     -Djava.security.auth.login.config=/path/to/jaas.conf \
     -Dsun.security.krb5.debug=true \
     SybaseKerberosTest
```

### Run (Windows)

Replace `:` with `;` in the classpath:

```bash
java -cp .;jconn4.jar ^
     -Djava.security.krb5.conf=C:\path\to\krb5.conf ^
     -Djava.security.auth.login.config=C:\path\to\jaas.conf ^
     -Dsun.security.krb5.debug=true ^
     SybaseKerberosTest
```

---

## Expected Output

### On success

```
Connecting...
SUCCESS! Result: 1
```

(Lots of Kerberos debug output will appear before this — that's normal with `krb5.debug=true`.)

### On failure

The last few lines of debug output will tell you what went wrong. See the troubleshooting section below.

---

## Troubleshooting

### Common errors and fixes

| Error message | Likely cause | Fix |
|---|---|---|
| `No credentials cache found` | `kinit` not run, or wrong user | Run `kinit` or check `whoami` |
| `Clock skew too great` | Client clock differs from KDC by >5 min | Sync time via NTP |
| `Server not found in Kerberos database` | Service principal name wrong | Verify with `kvno <principal>` |
| `KDC has no support for encryption type (14)` | KDC issuing weak encryption (RC4/DES) | Enable AES on Sybase service account in AD |
| `Cannot find KDC for realm` | `krb5.conf` issue | Check `[realms]` and `[domain_realm]` sections |
| `module ... does not export ... to unnamed module` | Java 17 module restrictions | Add `--add-opens` flag (see below) |

### Java 17 module flag (if needed)

If you see module-related errors, add this to the `java` command:

```bash
--add-opens java.security.jgss/sun.security.krb5=ALL-UNNAMED
```

### Debug order

If the connection fails, debug in this order:

1. Can you `kinit` successfully? (Kerberos basics work)
2. Does `klist` show a valid TGT?
3. Does `klist -e` show AES encryption?
4. Can you `kvno <sybase-service-principal>`? (Sybase is registered)
5. Does Java's debug output show a ticket being obtained?
6. Does the JDBC connection then fail? (JDBC/Sybase config issue)

---

## Reference: krb5.conf checklist

Open your `krb5.conf` and confirm:

- `default_realm` is set to your Kerberos realm (uppercase, e.g., `EXAMPLE.COM`)
- `[realms]` section has the correct `kdc =` hostname and port
- `[domain_realm]` maps your Sybase server's domain to the realm

Example structure:

```
[libdefaults]
    default_realm = EXAMPLE.COM

[realms]
    EXAMPLE.COM = {
        kdc = kdc.example.com:88
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM
```

---

## Notes

- No `Class.forName()` needed — modern JDBC (Java 6+) auto-loads drivers from classpath
- No username/password in code — Kerberos handles authentication via the ticket cache
- `try-with-resources` closes `Connection`, `Statement`, and `ResultSet` automatically
- The Sybase service principal must be registered in Kerberos (set with `-s` option when Sybase server starts)
- JCE Unlimited Strength is built into Java 17 — no separate download needed

---

## What's Verified

This guide has been verified against:

- Oracle Java 17 official documentation (`Krb5LoginModule`)
- SAP jConnect for JDBC 16.0 documentation
- Common Java 17 Kerberos issues and solutions
