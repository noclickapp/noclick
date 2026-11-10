The DAG-run list fixture is the exact expected response in Apache Airflow 2.10.0 `TestGetDagRuns.test_should_respond_200`, with `self.default_time` and `self.default_time_2` expanded from the upstream class. Source: https://github.com/apache/airflow/blob/2.10.0/tests/api_connexion/endpoints/test_dag_run_endpoint.py

The API shape and poll ordering are pinned by https://airflow.apache.org/docs/apache-airflow/2.10.0/_specs/v1.yaml (`get_dag_runs`, `DAGRunCollection`, `DAGRun`). Apache-2.0.
