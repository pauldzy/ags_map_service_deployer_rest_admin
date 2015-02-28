A full rewrite of my map service deployer script which attempts to replace the reliance on AGS arcpy interactons with equivalent REST admin APIs calls.

This is a work in progress but the basic components all function correctly.  The sticking point is reverse engineering the JSON information needed to provide to the publishing service to deploy the SD. For example you need to check manually if the service you are deploying already exists and if so, alter the SD json dump accordingly. 

Consider this version 0.0.2
