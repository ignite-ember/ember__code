plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "2.1.0"
    id("org.jetbrains.intellij.platform") version "2.2.1"
}

group = "sh.igniteember"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        intellijIdeaCommunity("2024.2.4")
    }
}

kotlin {
    jvmToolchain(17)
}

// Bundle the shared web UI (clients/web/dist) into plugin resources.
// Run `npm --prefix ../web run build` first (or wire it into CI).
val prepareWebUi by tasks.registering(Copy::class) {
    from(layout.projectDirectory.dir("../web/dist"))
    into(layout.buildDirectory.dir("resources/main/webui"))
}

tasks.named("processResources") {
    dependsOn(prepareWebUi)
}

intellijPlatform {
    pluginConfiguration {
        name = "Ember Code"
        ideaVersion {
            sinceBuild = "242"
        }
    }
}
