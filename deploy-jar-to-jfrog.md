# Deploying a Maven JAR to JFrog Artifactory

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

## Note

Repo names vary by company. Check **Artifacts** in the JFrog UI for the exact names, and replace `libs-release-local` / `libs-snapshot-local` if yours are different.
