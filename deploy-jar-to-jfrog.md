# Deploying a Maven JAR to JFrog Artifactory

## 0. Create a basic Maven project (optional)

Check your Java version first:

```bash
java -version
mvn -v
```

> `mvn -v` shows the Java version Maven runs on. The version you set in the pom can't be higher than that.

Generate the project (change `17` to your Java version, such as `11` or `21`):

```bash
mvn archetype:generate \
  -DgroupId=com.example \
  -DartifactId=myapp \
  -DarchetypeArtifactId=maven-archetype-quickstart \
  -DarchetypeVersion=1.5 \
  -DjavaCompilerVersion=17 \
  -DinteractiveMode=false
```

> On Windows Command Prompt, put it all on one line or use `^` instead of `\` at the line ends.

Project layout:

```
myapp/
├── pom.xml
└── src/
    ├── main/java/com/example/App.java
    └── test/java/com/example/AppTest.java
```

Check that the generated `pom.xml` contains:

```xml
<properties>
  <maven.compiler.release>17</maven.compiler.release>
</properties>
```

If it doesn't, add it yourself and remove any `maven.compiler.source` and `maven.compiler.target` lines.

Build the JAR:

```bash
cd myapp
mvn clean package
```

The JAR is created at `target/myapp-1.0-SNAPSHOT.jar`.

## 1. Configure `pom.xml`

Add this inside `<project>`:

```xml
<distributionManagement>
  <repository>
    <id>artifactory</id>
    <url>https://YOURCOMPANY.jfrog.io/artifactory/libs-release-local</url>
  </repository>
  <snapshotRepository>
    <id>artifactory</id>
    <url>https://YOURCOMPANY.jfrog.io/artifactory/libs-snapshot-local</url>
  </snapshotRepository>
</distributionManagement>
```

## 2. Add credentials to `~/.m2/settings.xml`

Create the file if it doesn't exist:

```xml
<settings>
  <servers>
    <server>
      <id>artifactory</id>
      <username>YOUR_USERNAME</username>
      <password>YOUR_ACCESS_TOKEN</password>
    </server>
  </servers>
</settings>
```

> The `<id>` must match the `<id>` in `pom.xml`.
> Use an access token instead of your password: in JFrog, open your profile → **Generate Token**.

## 3. Deploy

```bash
mvn clean deploy
```

Maven picks the repo from the project version:

| Version | Goes to |
|---|---|
| `1.0.0` | `libs-release-local` |
| `1.0.0-SNAPSHOT` | `libs-snapshot-local` |

## Troubleshooting

| Error | Cause / Fix |
|---|---|
| **401 Unauthorized** | Wrong username or token, or the `<id>` values don't match |
| **403 Forbidden** | Your user lacks deploy permission on that repo |
| **405 Method Not Allowed** | URL points to a virtual or remote repo. Use the `-local` one |
| **409 Conflict** | That release version already exists. Increase the version number |

## Optional: Deploy a JAR you already built, without changing the pom

```bash
mvn deploy:deploy-file \
  -Dfile=target/myapp-1.0.0.jar \
  -DgroupId=com.example \
  -DartifactId=myapp \
  -Dversion=1.0.0 \
  -Dpackaging=jar \
  -DrepositoryId=artifactory \
  -Durl=https://YOURCOMPANY.jfrog.io/artifactory/libs-release-local
```

## Finding which `settings.xml` you're using

Maven reads two settings files. If a setting is in both, the user file wins.

| Type | Location |
|---|---|
| **User** | `~/.m2/settings.xml` (Windows: `C:\Users\YOU\.m2\settings.xml`) |
| **Global** | `<maven home>/conf/settings.xml` (run `mvn -v` and check the `Maven home:` line) |

### Show the exact paths

Linux / macOS:

```bash
mvn -X help:help | grep -i settings
```

Windows:

```bash
mvn -X help:help | findstr /i settings
```

Output looks like:

```
[DEBUG] Reading global settings from /opt/maven/conf/settings.xml
[DEBUG] Reading user settings from /home/you/.m2/settings.xml
```

### Check that your credentials are picked up

```bash
mvn help:effective-settings
```

This prints the combined settings Maven is actually using. Look for the `<server>` with `id` `artifactory`. The password is masked.

### When the paths change

- If Maven runs with `-s` (user settings) or `-gs` (global settings), it uses the file given there.
- In IntelliJ or Eclipse, the IDE may use its own settings file. Check the IDE's Maven preferences.

## Note

Repo names vary by company. Check **Artifacts** in the JFrog UI for the exact names, and replace `libs-release-local` / `libs-snapshot-local` if yours are different.
