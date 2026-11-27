// Delivery pipeline (§21): checkout -> build & tag by SHA -> push -> deploy to the test cluster -> smoke test
// -> (nightly) full evaluation vs baseline. Any failing stage stops the pipeline; on failure unhealthy rollouts are undone.
pipeline {
  agent any
  options { timestamps(); disableConcurrentBuilds(); timeout(time: 60, unit: 'MINUTES') }
  triggers {
    pollSCM('H/2 * * * *')      // a webhook cannot reach a laptop; poll main every 2 minutes
    cron('H 2 * * *')           // nightly evaluation
  }
  environment {
    TAG = "${env.GIT_COMMIT.take(7)}"
    REGISTRY = credentials('registry-url')        // e.g. localhost:5001 or ghcr.io/<org>/<repo>
  }
  stages {
    stage('Checkout') { steps { checkout scm } }
    stage('Build')    { steps { sh './scripts/build_images.sh $TAG' } }
    stage('Push') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'registry', usernameVariable: 'U', passwordVariable: 'P')]) {
          sh 'echo "$P" | docker login "$REGISTRY" -u "$U" --password-stdin && ./scripts/push_images.sh $TAG'
        }
      }
    }
    stage('Deploy') {
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-test', variable: 'KUBECONFIG')]) {
          sh './scripts/deploy.sh $TAG'          // kubectl rollout status --timeout=180s fails the stage
        }
      }
    }
    stage('Smoke') {
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-test', variable: 'KUBECONFIG')]) {
          sh './scripts/smoke_test.sh'
        }
      }
    }
    stage('Eval') {
      when { triggeredBy 'TimerTrigger' }
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-test', variable: 'KUBECONFIG')]) {
          sh '''
            kubectl -n idea-validator delete job eval-job --ignore-not-found
            kubectl kustomize k8s/overlays/test >/dev/null
            sed "s#registry/evaluation:set-by-deploy#$REGISTRY/evaluation:$TAG#" k8s/base/jobs/eval-job.yaml | kubectl apply -f -
            ./scripts/check_eval.sh
          '''
        }
      }
    }
  }
  post {
    failure {
      echo 'Pipeline failed, nothing promoted'
      withCredentials([file(credentialsId: 'kubeconfig-test', variable: 'KUBECONFIG')]) {
        sh './scripts/rollback_if_needed.sh || true'
      }
    }
  }
}
