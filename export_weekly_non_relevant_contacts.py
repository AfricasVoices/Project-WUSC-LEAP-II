import argparse
import csv
import importlib

from core_data_modules.cleaners import Codes
from core_data_modules.logging import Logger
from core_data_modules.traced_data.io import TracedDataJsonIO
from core_data_modules.analysis import analysis_utils, AnalysisConfiguration

log = Logger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exports contacts who sent 'Non relevant' messages"
                                                 "in the target week question")

    parser.add_argument("google_cloud_credentials_file_path", metavar="google-cloud-credentials-file-path",
                        help="Path to a Google Cloud service account credentials file to use to access the "
                             "credentials bucket"),
    parser.add_argument("configuration_module",
                        help="Configuration module to import e.g. 'configurations.test_config'. "
                             "This module must contain a PIPELINE_CONFIGURATION property")
    parser.add_argument("traced_data_paths", metavar="traced-data-paths", nargs="+",
                        help="Paths to the traced data files (either messages or individuals) to extract phone "
                             "numbers from")
    parser.add_argument("target_raw_dataset", metavar="target-raw-dataset",
                        help="Target raw dataset name to check for message relevance from")
    parser.add_argument("csv_output_dir_path", metavar="csv-output-file-path",
                        help="Path to a CSV file to write the contacts from the locations of interest to. "
                             "Exported file is in a format suitable for direct upload to Rapid Pro")

    args = parser.parse_args()

    google_cloud_credentials_file_path = args.google_cloud_credentials_file_path
    pipeline_config = importlib.import_module(args.configuration_module).PIPELINE_CONFIGURATION
    traced_data_paths = args.traced_data_paths
    target_raw_dataset = args.target_raw_dataset
    csv_output_dir_path = args.csv_output_dir_path

    pipeline = pipeline_config.pipeline_name

    uuid_table = pipeline_config.uuid_table.init_uuid_table_client(google_cloud_credentials_file_path)

    uuids = set()
    for path in traced_data_paths:
        log.info(f"Loading previous traced data from file '{path}'...")
        with open(path) as f:
            data = TracedDataJsonIO.import_jsonl_to_traced_data_iterable(f)
        log.info(f"Loaded {len(data)} traced data objects")

        for td in data:
            if td["consent_withdrawn"] == Codes.TRUE:
                continue

            for analysis_dataset_config in pipeline_config.analysis.dataset_configurations:
                if analysis_dataset_config.raw_dataset == target_raw_dataset:
                    for coding_config in analysis_dataset_config.coding_configs:
                        label_key = f'{coding_config.analysis_dataset}_labels'

                        analysis_configurations = AnalysisConfiguration(analysis_dataset_config.raw_dataset,
                                                                        analysis_dataset_config.raw_dataset,
                                                                        label_key,
                                                                        coding_config.code_scheme)

                        codes = analysis_utils.get_codes_from_td(td, analysis_configurations)

                        if not analysis_utils.relevant(td, "consent_withdrawn", analysis_configurations):
                            for code in codes:
                                if code.string_value in ["showtime_question", "greeting", "opt_in",
                                                         "about_conversation", "gratitude", "question",  "NC"]:
                                    uuids.add(td["participant_uuid"])

    log.info(f"Found {len(uuids)} participants who sent non relevant messages in {target_raw_dataset}")

    log.info(f"Converting {len(uuids)} NC uuids to urns...")
    nc_urn_lut = uuid_table.uuid_to_data_batch(uuids)
    nc_urns = {nc_urn_lut[uuid] for uuid in uuids}
    log.info(f"Converted {len(uuids)} to {len(nc_urns)}")

    # Export contacts CSV
    log.warning(f"Exporting {len(nc_urns)} urns to {csv_output_dir_path}...")
    csv_output_file_path = f'{csv_output_dir_path}/{target_raw_dataset}_nc_contacts.csv'
    with open(csv_output_file_path, "w") as f:
        urn_namespaces = {urn.split(":")[0] for urn in nc_urns}
        headers = [f"URN:{namespace}" for namespace in urn_namespaces]

        writer = csv.DictWriter(f, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for urn in nc_urns:
            namespace = urn.split(":")[0]
            value = urn.split(":")[1]
            writer.writerow({
                f"URN:{namespace}": value
            })

        log.info(f"Wrote {len(nc_urns)} urns to {csv_output_file_path}")
