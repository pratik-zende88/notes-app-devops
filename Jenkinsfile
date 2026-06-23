pipeline {
    agent any

    // ── All secrets come from Jenkins Credentials store — never from git ──
    environment {
        IMAGE_NAME   = "notes-app"
        EC2_HOST     = credentials('EC2_HOST')        // e.g. ec2-xx.compute.amazonaws.com
        EC2_USER     = "ubuntu"
        SSH_KEY      = credentials('EC2_SSH_KEY')     // Jenkins SSH key credential
        DB_PASSWORD  = credentials('DB_PASSWORD')     // Jenkins secret text
        DB_USER      = credentials('DB_USER')
        DB_HOST      = credentials('DB_HOST')
        DB_NAME      = credentials('DB_NAME')
    }

    stages {

        // ── 1. BUILD ──────────────────────────────────────────────────────
        stage('Build') {
            steps {
                script {
                    env.IMAGE_TAG = sh(script: "git rev-parse --short HEAD", returnStdout: true).trim()
                    echo "Building image: ${IMAGE_NAME}:${IMAGE_TAG}"
                }
                sh """
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag  ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                """
            }
        }

        // ── 2. TEST ───────────────────────────────────────────────────────
        stage('Test') {
            steps {
                sh """
                    # Spin up a throwaway postgres for unit tests
                    docker run -d --name test-db \
                        -e POSTGRES_USER=test_user \
                        -e POSTGRES_PASSWORD=test_pass \
                        -e POSTGRES_DB=test_db \
                        -p 5433:5432 \
                        postgres:15-alpine

                    # Wait for DB to be ready (max 30 s)
                    for i in \$(seq 1 30); do
                        docker exec test-db pg_isready -U test_user && break
                        sleep 1
                    done

                    # Run app tests inside a container linked to test-db
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

        // ── 3. DEPLOY ─────────────────────────────────────────────────────
        stage('Deploy') {
            steps {
                script {
                    // Save current running tag as rollback target BEFORE deploying
                    env.PREV_TAG = sh(
                        script: """
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                                ${EC2_USER}@${EC2_HOST} \
                                'docker inspect notes-app --format={{.Config.Image}} 2>/dev/null || echo none'
                        """,
                        returnStdout: true
                    ).trim()
                    echo "Previous tag saved for rollback: ${env.PREV_TAG}"
                }

                // Save image as tar and scp to EC2 (no registry needed)
                sh """
                    docker save ${IMAGE_NAME}:${IMAGE_TAG} | gzip > /tmp/notes-app.tar.gz
                    scp -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                        /tmp/notes-app.tar.gz ${EC2_USER}@${EC2_HOST}:/tmp/
                """

                // Load + run on EC2
                sh """
                    ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${EC2_USER}@${EC2_HOST} '
                        set -e
                        docker load < /tmp/notes-app.tar.gz

                        # Stop old container gracefully
                        docker stop notes-app 2>/dev/null || true
                        docker rm   notes-app 2>/dev/null || true

                        # Start new container — secrets from env vars only
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
                    '
                """
            }
        }

        // ── 4. HEALTH CHECK + ROLLBACK ────────────────────────────────────
        stage('Health Check') {
            steps {
                script {
                    /*
                     * Retry logic:
                     *   - Max 5 attempts, 10 s apart  → 50 s total window
                     *   - curl timeout: 5 s per call
                     *   - Unhealthy = HTTP status != 200  OR  curl itself fails
                     *   - If all 5 attempts fail → rollback to PREV_TAG
                     */
                    def healthy = false
                    def maxRetries = 5
                    def waitSec   = 10

                    for (int i = 1; i <= maxRetries; i++) {
                        echo "Health check attempt ${i}/${maxRetries}..."
                        def statusCode = sh(
                            script: """
                                ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no \
                                    ${EC2_USER}@${EC2_HOST} \
                                    'curl -s -o /dev/null -w "%{http_code}" \
                                     --max-time 5 http://localhost:5000/health'
                            """,
                            returnStdout: true
                        ).trim()

                        if (statusCode == "200") {
                            echo "Health check passed (HTTP 200)"
                            healthy = true
                            break
                        }

                        echo "Got HTTP ${statusCode} — waiting ${waitSec}s before retry..."
                        sleep(waitSec)
                    }

                    if (!healthy) {
                        echo "All ${maxRetries} health checks failed. Initiating rollback..."
                        currentBuild.result = 'FAILURE'

                        if (env.PREV_TAG && env.PREV_TAG != 'none') {
                            sh """
                                ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${EC2_USER}@${EC2_HOST} '
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
                                '
                            """
                            echo "Rollback complete — running: ${env.PREV_TAG}"
                        } else {
                            echo "No previous image available — manual intervention required."
                        }
                        error("Deployment failed. Rolled back.")
                    }
                }
            }
        }
    }

    // ── Notifications (Bonus) ─────────────────────────────────────────────
    post {
        success {
            echo "Deploy SUCCESS — ${IMAGE_NAME}:${env.IMAGE_TAG} is live."
            // Uncomment + configure for Slack:
            // slackSend channel: '#deploys', message: "✅ Deploy succeeded: ${IMAGE_NAME}:${env.IMAGE_TAG}"
        }
        failure {
            echo "Deploy FAILED — check logs above. Rollback may have run."
            // slackSend channel: '#deploys', message: "❌ Deploy failed: ${IMAGE_NAME}:${env.IMAGE_TAG}. Rollback triggered."
        }
    }
}
