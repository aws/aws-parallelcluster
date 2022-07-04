plugins {
    java
    id("software.amazon.smithy").version("0.6.0")
}

repositories {
    mavenLocal()
    mavenCentral()
}

buildscript {
    dependencies {
        classpath("software.amazon.smithy:smithy-openapi:1.22.0")
        classpath("software.amazon.smithy:smithy-aws-traits:1.22.0")
        classpath("software.amazon.smithy:smithy-aws-apigateway-openapi:1.22.0")
    }
}

dependencies {
    implementation("software.amazon.smithy:smithy-aws-apigateway-traits:1.22.0")
    implementation("software.amazon.smithy:smithy-aws-traits:1.22.0")
    implementation("software.amazon.smithy:smithy-model:1.22.0")
    implementation("software.amazon.smithy:smithy-linters:1.22.0")
}

tasks["jar"].enabled = false
