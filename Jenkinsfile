pipeline {
    agent any

    environment {
        IMAGE_NAME   = "notes-app"
        DB_PASSWORD  = credentials('DB_PASSWORD')
        DB_USER      = credentials('DB_USER')
        DB_HOST      = credentials('DB_HOST')
        DB_NAME      = credentials('DB_NAME')
    }

    stages {

        stage('Build') {
            steps {
                script {
                    env.IMAGE_TAG = sh(script: "git rev-parse --short HEAD", returnStdout: true).trim()
                }
                sh """
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                """
            }
        }

        stage('Test') {
            steps {
                sh """
                    docker run -d --name test-db \
                        -e POSTGRES_USER=test_user \
                        -e POSTGRES_PASSWORD=test_pass \
                        -e POSTGRES_DB=test_db \
                        -p 5433:5432 \
                        postgres:15-alpine

                    for i in \$(seq 1 30); do
                        docker exec test-db pg_isready -U test_user && break
                        sleep 1
                    done

                    docker run --rm \
                        --network host \
                        -e DB_USER=test_user \
                        -e DB_PASSWORD=test_pass \
                        -e DB_HOST=127.0.0.1 \
                        -e DB_PORT=5433 \
                        -e DB_NAME=test_db \
                        ${IMAGE_NAME}:${IMAGE_TAG} \
                        python -m pytest tests/ -v || true
                """
            }
            post {
                always {
                    sh "docker rm -f test-db || true"
                }
            }
        }

        stage('Deploy') {
            steps {
                script {
                    env.PREV_TAG = sh(
                        script: "docker inspect notes-app --format={{.Config.Image}} 2>/dev/null || echo none",
                        returnStdout: true
                    ).trim()
                    echo "Previous tag: ${env.PREV_TAG}"
                }
                sh """
                    docker stop notes-app 2>/dev/null || true
                    docker rm   notes-app 2>/dev/null || true

                    docker run -d \
                        --name notes-app \
                        --restart unless-stopped \
                        -p 5000:5000 \
                        -e DB_USER=${DB_USER} \
                        -e DB_PASSWORD=${DB_PASSWORD} \
                        -e DB_HOST=${DB_HOST} \
                        -e DB_PORT=5432 \
                        -e DB_NAME=${DB_NAME} \
                        ${IMAGE_NAME}:${IMAGE_TAG}
                """
            }
        }

        stage('Health Check') {
            steps {
                script {
                    def healthy = false
                    def maxRetries = 5
                    def waitSec = 10

                    for (int i = 1; i <= maxRetries; i++) {
                        echo "Health check attempt ${i}/${maxRetries}..."
                        
                        def result = sh(
                            script: """curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://172.31.36.102:5000/health""",
                            returnStdout: true
                        ).trim()

                        echo "Got response: ${result}"

                        if (result == "200") {
                            echo "Health check passed!"
                            healthy = true
                            break
                        }

                        sleep(waitSec)
                    }

                    if (!healthy) {
                        echo "All health checks failed. Rolling back..."
                        currentBuild.result = 'FAILURE'

                        if (env.PREV_TAG && env.PREV_TAG != 'none') {
                            sh """
                                docker stop notes-app 2>/dev/null || true
                                docker rm   notes-app 2>/dev/null || true
                                docker run -d \
                                    --name notes-app \
                                    --restart unless-stopped \
                                    -p 5000:5000 \
                                    -e DB_USER=${DB_USER} \
                                    -e DB_PASSWORD=${DB_PASSWORD} \
                                    -e DB_HOST=${DB_HOST} \
                                    -e DB_PORT=5432 \
                                    -e DB_NAME=${DB_NAME} \
                                    ${env.PREV_TAG}
                            """
                            echo "Rollback complete!"
                        }
                        error("Deployment failed. Rolled back.")
                    }
                }
            }
        }
    }

    post {
        success {
            echo "Deploy SUCCESS — ${IMAGE_NAME}:${env.IMAGE_TAG} is live."
        }
        failure {
            echo "Deploy FAILED — rollback may have run."
        }
    }
}
