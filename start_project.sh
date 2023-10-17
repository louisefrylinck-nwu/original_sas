#!/bin/bash

#The purpose of this script is to automate (and simplify) the process of running a fake SAS with functionality tests
#Run 'bash start_project.sh' in your terminal to run this script.

#------------------------------------START HERE ------------------------------------#
#If this is your first time generating certificates for the fake SAS, open a new terminal (from path-to-spectrum-access-system)
#and run "bash initial_certificates_setup"

#If you have generated certificates, but your certificates expired, run  "bash replace_certificates.sh" in a separate terminal.
#The script 'replace_certificates.sh' will create a crl server on a different localhost port to help you manage certificates.
#It will give you some options, choose option 2 to delete all certs and replace them with new ones. 

#------------------------------------ After reading the above -----------------------------------#

#------------------------------------ CONTINUE HERE ------------------------------------#
# Directories
CERT_DIR="/certs"  # Change this to the directory where your certificates are stored
HARNESS_DIR="src/harness"     # Change this to the directory where your harness is located
SRC_DIR="src"                 # Change this to the directory where your src is located

echo 'Your SAS project is starting - say thank you!'


cd "$HARNESS_DIR"

#Open fake_sas.py
python fake_sas.py

#note to self: this may not be necessary if the crl server works properly, but it is plan B. 

#Run CBSD-SAS functionality tests


#############################################
#Check whether one certificate has expired. If one has expired, 
#delete all of them and generate new ones. 


# Function to check if any certificate has expired
# has_expired() {
#     for cert in "$CERT_DIR"/*.crt; do
#         if ! openssl x509 -checkend 0 -noout -in "$cert"; then
#             return 0  # True, a certificate has expired
#         else echo "Your certificates are up to date."
#         fi
#     done
#     return 1  # False, no certificates have expired
# }

# # If any certificate has expired, delete all of them
# if has_expired; then
#     echo "At least one certificate has expired. Deleting all certificates..."
#     rm -f "$CERT_DIR"/*.crt

    
#     # Generate new certificates
#     cd ..
#     cd "$CERT_DIR"
#     bash generate_fake_certs.sh
#     echo "New certificates generated."
# fi

# cd ..
# pwd

# Navigate to the harness directory 
# cd "$CERT_DIR"
# bash generate_fake_certs.sh



#Change paths
# OLD_PATH="/old/path/to/data"
# NEW_PATH="/new/path/to/data"
# FILE="config.py"

# sed -i "s|DATA_PATH = \"$OLD_PATH\"|DATA_PATH = \"$NEW_PATH\"|" $FILE

# python src/harness/fake_sas.py

#------------------------------------ END ------------------------------------#