#This script automatically navigates to the correct folder and generates fake certificates for the fake_sas.py file.
#Read 'start_project.sh' for more  info. 
 
cd src/harness/cert
    bash generate_fake_certs.sh
    echo "New certificates generated."