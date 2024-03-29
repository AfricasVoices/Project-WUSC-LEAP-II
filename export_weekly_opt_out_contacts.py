import argparse
import csv
import importlib

from core_data_modules.cleaners import Codes
from core_data_modules.logging import Logger
from core_data_modules.traced_data.io import TracedDataJsonIO

log = Logger(__name__)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exports opt out contacts from analysis Traced Data")

    parser.add_argument("google_cloud_credentials_file_path", metavar="google-cloud-credentials-file-path",
                        help="Path to a Google Cloud service account credentials file to use to access the "
                             "credentials bucket"),
    parser.add_argument("configuration_module",
                        help="Configuration module to import e.g. 'configurations.test_config'. "
                             "This module must contain a PIPELINE_CONFIGURATION property")
    parser.add_argument("traced_data_paths", metavar="traced-data-paths", nargs="+",
                        help="Paths to the traced data files (either messages or individuals) to extract phone "
                             "numbers from")
    parser.add_argument("csv_output_dir_path", metavar="csv-output-file-path",
                        help="Path to a CSV file to write the contacts from the locations of interest to. "
                             "Exported file is in a format suitable for direct upload to Rapid Pro")

    args = parser.parse_args()

    google_cloud_credentials_file_path = args.google_cloud_credentials_file_path
    pipeline_config = importlib.import_module(args.configuration_module).PIPELINE_CONFIGURATION
    traced_data_paths = args.traced_data_paths
    csv_output_dir_path = args.csv_output_dir_path

    pipeline = pipeline_config.pipeline_name

    uuid_table = pipeline_config.uuid_table.init_uuid_table_client(google_cloud_credentials_file_path)

    opt_out_uuids = set()
    for path in traced_data_paths:
        log.info(f"Loading previous traced data from file '{path}'...")
        with open(path) as f:
            data = TracedDataJsonIO.import_jsonl_to_traced_data_iterable(f)
        log.info(f"Loaded {len(data)} traced data objects")

        for td in data:
            if td["consent_withdrawn"] == Codes.TRUE:
                opt_out_uuids.add(td["participant_uuid"])

    log.info(f"Converting {len(opt_out_uuids)} Opt out uuids to urns...")
    opt_out_urn_lut = uuid_table.uuid_to_data_batch(opt_out_uuids)
    opt_out_urns = {opt_out_urn_lut[uuid] for uuid in opt_out_uuids}
    log.info(f"Converted {len(opt_out_uuids)} to {len(opt_out_urns)} urns")

    # Export contacts CSV
    log.warning(f"Exporting {len(opt_out_urns)} urns to {csv_output_dir_path}...")
    csv_output_file_path = f'{csv_output_dir_path}/{pipeline_config.pipeline_name}_opt_out_contacts.csv'
    with open(csv_output_file_path, "w") as f:
        urn_namespaces = {urn.split(":")[0] for urn in opt_out_urns}
        headers = [f"URN:{namespace}" for namespace in urn_namespaces]

        writer = csv.DictWriter(f, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for urn in opt_out_urns:
            namespace = urn.split(":")[0]
            value = urn.split(":")[1]
            writer.writerow({
                f"URN:{namespace}": value
            })
        log.info(f"Wrote {len(opt_out_urns)} urns to {csv_output_file_path}")
