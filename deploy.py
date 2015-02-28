import arcpy
import os,sys
import xml.dom.minidom as DOM;
import httplib
import urllib,urllib2,mimetools,mimetypes
import json,stat
import getpass
import time
from cStringIO import StringIO

###############################################################################
#                                                                             #
# ArcGIS Server Mapping Service Deployer Script                               #
# Version: 20150220                                                           #
#                                                                             #
#  The script takes two optional parameters, the first being the name of the  #
#  ArcCatalog administration connection for the AGS Server and the second     #
#  being the name of the SDE database connection to be used by the mapping    #
#  service.                                                                   #
#                                                                             #
#  You may provide default connection names below.  Note all security         #
#  is thus handled by the connections.  Obviously there is room here for      #
#  errors if you are continually swapping around these names (e.g. deploying  #
#  to the wrong server drawing from the wrong database).  I would advise      #
#  against hard coding these to your production server connections.           #
#                                                                             #
#  In order to change data source paths its necessary to alter the MXD        #
#  before deployment.  Thus this script creates a temporary copy of the MXD   #
#  in order to change the paths.  The original MXD is never modified.         #
#                                                                             #
###############################################################################

# The location of your MXD file to be deployed to AGS
mxd = "BEACON_NAD83.mxd";

# The name of the AGS Service to deploy the MXD as
# Note existing services will be overwritten
service  = "BEACON_NAD83";

# The AGS folder into which to deploy the service.
# Leave None to deploy to the root.
ags_folder = "OWPROGRAM";

# Hash of general properties to be applied
ags_properties = {
    'enableDynamicLayers': True
   ,'schemaLockingEnabled': False
   ,'MinInstances': 3
   ,'MaxInstances': 5
}

# Hash of services to enable or disable
ags_services = {
    'WMSServer': False
   ,'WFSServer': False
   ,'KmlServer': False
}

# Array of Hash of properties to be applied to individual services
ags_service_props = {}

# Values to use in overriding the text provided by the MXD.
ags_summary = None;
ags_tags    = None;
  
debug = True;

###############################################################################
#                                                                             #
#  Step 10                                                                    #
#  Section to load the AGS Admin credentials                                  #
#  If you only use https, you may want to change the default port to 6443     #
#                                                                             #
###############################################################################
if len(sys.argv) > 1:
   ags_admin = sys.argv[1];
else:
   ags_admin = raw_input("Enter AGS admin user name: ");
   
if len(sys.argv) > 2:
   ags_password = sys.argv[2];
else:
   ags_password = getpass.getpass("Enter AGS admin password: ");

if len(sys.argv) > 3:
   ags_server = sys.argv[3];
else:
   ags_server = raw_input("Enter AGS server url (e.g. http://watersgeo.epa.gov) : ");
   
if len(sys.argv) > 4:
   ags_port = sys.argv[4];
else:
   ags_port = raw_input("Enter port number [6080]: ") or "6080";

###############################################################################
#                                                                             #
#  Step 20                                                                    #
#  Data Source Remappings                                                     #
#  This section can be altered as needed to populate the                      #
#  sde_replacements and folder_replacements object lists                      #
#                                                                             #
###############################################################################
class sde_replacement:
   source_name   = None;
   source        = None;
   
   dest_name     = None;
   destination   = None;
   dest_username = None;
   dest_instance = None;
   
   def __init__(self,source,destination):
      self.source_name = source;
      self.dest_name   = destination;
      self.source      = "Database Connections\\" + self.source_name + ".sde";
      self.destination = "Database Connections\\" + self.dest_name + ".sde";
      
   def verify_local_destination(self):
      if not arcpy.Exists(self.destination):
         arcpy.AddMessage("  Connection named " + self.destination+ " not found.");
         con2_sde = os.environ['USERPROFILE'] + "\\AppData\\Roaming\\ESRI\\Desktop10.3\\ArcCatalog\\" + self.dest_name + ".sde"
         
         if arcpy.Exists(con2_sde):
            self.destination = con2_sde;
            
         else:
            arcpy.AddMessage("  No luck checking " + con2_sde);
            con3_sde = os.environ['USERPROFILE'] + "\\AppData\\Roaming\\ESRI\\Desktop10.2\\ArcCatalog\\" + self.dest_name + ".sde"
            
            if arcpy.Exists(con3_sde):
               self.destination = con3_sde;
            
            else:  
               arcpy.AddMessage("  No luck checking " + con3_sde);
               arcpy.AddMessage("  Unable to find a valid connection for " + self.dest_name);
               return False;
               
      return True;
      
   def get_destination_credentials(self):
      if not arcpy.Exists(self.destination):
         arcpy.AddMessage("ERROR: unable to find " + self.dest_name);
         return False;
         
      arcpy.env.workspace = self.destination;
      desc = arcpy.Describe(self.destination);
      
      if desc is not None   \
      and hasattr(desc,"connectionProperties"):
         cp = desc.connectionProperties;
      else:
         arcpy.AddMessage("ERROR: unable to query SDE connection.");
         return False;

      self.dest_username = cp.user;
      self.dest_instance = cp.instance;
      return True;
      
class folder_replacement:
   source_folder      = None;
   destination_ds     = None;
   destination_folder = None;
   
   def __init__(self,source_folder,destination_ds):
      self.source_folder  = source_folder;
      self.destination_ds = destination_ds;

sde_replacements  = [];

if len(sys.argv) > 5:
   val = sys.argv[5];
else:
   val = raw_input("Enter the SDE connection name for beacon_ags Oracle schema: ");

sde_replacements.append(sde_replacement(
    "beacon_ags"
   ,val
));
  
folder_replacements = [];   

if len(sys.argv) > 6:
   val = sys.argv[6];
else:
   val = raw_input("Enter the AGS folder data store name [WatersData]: ") or "WatersData";

folder_replacements.append(folder_replacement(
    "\\\\industux\\WatersGeoAGS\\WatersData"
    ,val
));
folder_replacements = [];
###############################################################################
#                                                                             #
#  Step 30                                                                    #
#  The remaining sections of the script should not require modifications.     #
#  These functions are used to modify the sddraft xml file                    #
#                                                                             #
###############################################################################
def srv_property(doc,property,value):
   keys = doc.getElementsByTagName('Key')
   for key in keys:
      if key.hasChildNodes():
         if key.firstChild.data == property:
            if value is True:
               key.nextSibling.firstChild.data = 'true';
            elif value is False:
               key.nextSibling.firstChild.data = 'false';
            else:
               key.nextSibling.firstChild.data = value
   return doc;
  
def soe_enable(doc,soe,value):
   typeNames = doc.getElementsByTagName('TypeName');
   
   for typeName in typeNames:
      if typeName.firstChild.data == soe:
         extension = typeName.parentNode
         for extElement in extension.childNodes:
            if extElement.tagName == 'Enabled':
               if value is True:
                  extElement.firstChild.data = 'true';
               else:
                  extElement.firstChild.data = 'false';
                  
   return doc;

def soe_property(doc,soe,soeProperty,soePropertyValue):
   typeNames = doc.getElementsByTagName('TypeName');
   
   for typeName in typeNames:
       if typeName.firstChild.data == soe:
           extension = typeName.parentNode
           for extElement in extension.childNodes:
               if extElement.tagName in ['Props','Info']:
                   for propArray in extElement.childNodes:
                       for propSet in propArray.childNodes:
                           for prop in propSet.childNodes:
                               if prop.tagName == "Key":
                                   if prop.firstChild.data == soeProperty:
                                       if prop.nextSibling.hasChildNodes():
                                           prop.nextSibling.firstChild.data = soePropertyValue
                                       else:
                                           txt = doc.createTextNode(soePropertyValue)
                                           prop.nextSibling.appendChild(txt)
   return doc;

###############################################################################
#                                                                             #
#  Step 40                                                                    #
#  Define the workspace                                                       #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");

wrkspc = os.getcwd() + os.sep;
arcpy.AddMessage("  Workspace = " + wrkspc);
os.chdir(wrkspc);

###############################################################################
#                                                                             #
#  Step 50                                                                    #
#  Verify the MXD                                                             #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");

if not os.path.exists(wrkspc + mxd):
   arcpy.AddMessage("MXD file not found: " + wrkspc + mxd);
   exit(-1);
mapDoc = arcpy.mapping.MapDocument(wrkspc + mxd)
arcpy.AddMessage("  Orig MXD = " + wrkspc + mxd);

###############################################################################
#                                                                             #
#  Step 60                                                                    #
#  Validate the AGS Server connection                                         #
#  The token obtained is then used throughout the process.                    #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");

def getToken(username,password,serverName,serverPort):
   tokenURL = "/arcgis/admin/generateToken";
    
   params = urllib.urlencode({
       'username': username
      ,'password': password
      ,'client': 'requestip'
      ,'f': 'json'
   });
    
   headers = {
       "Content-type":"application/x-www-form-urlencoded"
      ,"Accept":"text/plain"
   };
   
   httpConn = httplib.HTTPConnection(serverName, serverPort);
   httpConn.request("POST", tokenURL, params, headers);
    
   response = httpConn.getresponse()
   if (response.status != 200):
      httpConn.close();
      arcpy.AddMessage("Error while fetch tokens from admin URL. Please check the URL and try again.");
      return;
      
   else:
      data = response.read();
      httpConn.close();
      token = json.loads(data) ;
      return token['token'];
    
try:
   token = getToken(
       username = ags_admin
      ,password = ags_password
      ,serverName = ags_server
      ,serverPort = ags_port
   );
   
except:
   arcpy.AddMessage("  ERROR: Could not generate an admin token with the username and password provided."); 
   raise;

if token == "":
   arcpy.AddMessage("  ERROR: Could not generate an admin token with the username and password provided."); 
   exit(-99);     

arcpy.AddMessage("  ArcGIS Server: " + ags_server);
arcpy.AddMessage("    Username: " + ags_admin);

###############################################################################
#                                                                             #
#  Step 70                                                                    #
#  Functions to execute json queries against AGS                              #
#                                                                             #
###############################################################################
def assertJsonSuccess(data):
   obj = json.loads(data)
   if 'status' in obj and obj['status'] == "error":
      return False;
   else:
      return True;

def fetchJson(ags_server,ags_port,token,serviceURL,addParams=None):
   headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"};
   
   baseParams = {'token': token, 'f': 'json'};
   if addParams is not None:
      baseParams.update(addParams);
   params = urllib.urlencode(baseParams);
   
   httpConn = httplib.HTTPConnection(ags_server, ags_port);
   httpConn.request("POST", serviceURL, params, headers);
   
   response = httpConn.getresponse();
   if (response.status != 200):
      httpConn.close();
      raise NameError("Could not read service info information.");

   data = response.read();
   if not assertJsonSuccess(data):
      raise NameError("Error when reading service information. " + str(data));
   
   dataObj = json.loads(data);
   httpConn.close();

   return dataObj;

###############################################################################
#                                                                             #
#  Step 80                                                                    #
#  Read the data store details from AGS                                       #
#                                                                             #
###############################################################################
class database_data_store:
   datastore_name     = None;
   publisher_username = None;
   publisher_instance = None;
   publisher_database = None;
   server_username    = None;
   server_instance    = None;
   server_database    = None;
   remapped           = False;
   
   def __init__(self,ds):
      if ds["path"]:
         self.datastore_name = ds["path"].replace("/enterpriseDatabases/","");

      if ds["info"]:
         if "connectionString" in ds["info"]:
            connection_string = ds["info"]["connectionString"];
            csItems = connection_string.split(";");
            for item in csItems:
               (key,value) = item.split("=");
               if key == "USER":
                  self.server_username = value;
               if key == "INSTANCE":
                  self.server_instance = value;
               if key == "DATABASE":
                  self.server_database = value;
      
         if "clientConnectionString" in ds["info"]:
            connection_string = ds["info"]["clientConnectionString"];
            csItems = connection_string.split(";");
            for item in csItems:
               (key,value) = item.split("=");
               if key == "USER":
                  self.publisher_username = value;
               if key == "INSTANCE":
                  self.publisher_instance = value;
               if key == "DATABASE":
                  self.publisher_database = value;
               
         else:
            self.publisher_username = self.server_username;
            self.publisher_instance = self.server_instance;
            self.publisher_database = self.server_database;
      
      if self.publisher_username == self.server_username   \
      and self.publisher_instance == self.server_instance:
         self.remapped = True;
      
class folder_data_store:
   datastore_name     = None;
   publisher_folder   = None;
   server_folder      = None;
   
   def __init__(self,ds):
      if ds["path"]:
         self.datastore_name = ds["path"].replace("/fileShares/","");
         
      if ds["info"]:
         if "path" in ds["info"]:
            self.server_folder = ds["info"]["path"];
            
      if ds["clientPath"]:
         self.publisher_folder = ds["clientPath"];
         
      else:
         self.publisher_folder = self.server_folder;
         
ds_db = fetchJson(
    ags_server = ags_server
   ,ags_port   = ags_port
   ,token      = token
   ,serviceURL = "/arcgis/admin/data/findItems"
   ,addParams  = {"parentPath":"/enterpriseDatabases"}
);

ags_ds_databases = [];
for ds in ds_db["items"]:
   obj = database_data_store(ds);
   ags_ds_databases.append(obj);
arcpy.AddMessage("    Database Data Stores: " + str(len(ags_ds_databases)));

ds_fl = fetchJson(
    ags_server = ags_server
   ,ags_port   = ags_port
   ,token      = token
   ,serviceURL = "/arcgis/admin/data/findItems"
   ,addParams  = {"parentPath":"/fileShares"}
);

ags_ds_folders = [];
for ds in ds_fl["items"]:
   ags_ds_folders.append(folder_data_store(ds));
arcpy.AddMessage("    Folder Data Stores: " + str(len(ags_ds_folders)));
   
###############################################################################
#                                                                             #
#  Step 90                                                                    #
#  Validate the SDE Server connections                                        #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
if len(sde_replacements) == 0:
   arcpy.AddMessage("  No SDE replacements to process.");
   
else:
   for item in sde_replacements:
      if item.verify_local_destination():
         arcpy.AddMessage("  SDE Connection File: " + item.destination);
      else:
         arcpy.AddMessage("  ERROR Could not find SDE Connection File : " + item.dest_name);
         exit(-1);
           
      if item.get_destination_credentials():
         arcpy.AddMessage("     Username: " + item.dest_username);
         arcpy.AddMessage("     Instance: " + item.dest_instance);
      else:
         arcpy.AddMessage("  ERROR Could not query SDE Connection File : " + item.dest_name);
         exit(-1);
         
      ds_match = None;
      for ds in ags_ds_databases:
         if  item.dest_username == ds.publisher_username \
         and item.dest_instance == ds.publisher_instance:
            ds_match = ds.datastore_name;
            
      if ds_match is not None:
         arcpy.AddMessage("     AGS Data Store: " + ds_match);
      else:
         arcpy.AddMessage("     ERROR: Unable to find matching data store on AGS for this connection.");
         arcpy.AddMessage("     username = " + item.dest_username + " and instance = " + item.dest_instance);
         exit(-2);

###############################################################################
#                                                                             #
#  Step 100                                                                   #
#  Validate the AGS Folder connections                                        #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
if len(folder_replacements) == 0:
   arcpy.AddMessage("  No Folder replacements to process.");
   
else:
   for item in folder_replacements:
      ds_match = None;
      for ds in ags_ds_folders:
         if item.destination_ds == ds.datastore_name:
            ds_match = ds;
            
      if ds_match is not None:
         arcpy.AddMessage("  Folder data store exists on AGS: " + ds_match.datastore_name);
         arcpy.AddMessage("    From Publisher Folder: " + ds_match.publisher_folder);
         arcpy.AddMessage("    To Server Folder: " + ds_match.server_folder);
         item.destination_folder = ds_match.server_folder;
         
      else:
         arcpy.AddMessage("  ERROR: Unable to find matching data store on AGS for " + item.destination_ds);
         
###############################################################################
#                                                                             #
#  Step 110                                                                   #
#  Create a temporary copy of the MXD                                         #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");

tempMap = arcpy.CreateScratchName(
    os.path.splitext(mxd)[0]
   ,".mxd"
   ,None
   ,arcpy.env.scratchFolder
);

arcpy.AddMessage("  Temp MXD = " + tempMap);
mapDoc.saveACopy(tempMap);
mapDoc = arcpy.mapping.MapDocument(tempMap);

###############################################################################
#                                                                             #
#  Step 120                                                                   #
#  Alter the temporary MXD to use the new connections                         #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
for item in folder_replacements:
   mapDoc.findAndReplaceWorkspacePaths(
       item.source_folder
      ,item.destination_folder
      ,False
   );

for item in sde_replacements:
   mapDoc.findAndReplaceWorkspacePaths(
       item.source
      ,item.destination
      ,False
   );               
               
mapDoc.save();
arcpy.AddMessage("  Swapping in altered data sources to temp MXD.");

###############################################################################
#                                                                             #
#  Step 130                                                                   #
#  Define the sddraft and sd temp files                                       #
#                                                                             #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");

sddraft = arcpy.CreateScratchName(
    service
   ,".sddraft"
   ,None
   ,arcpy.env.scratchFolder
);

sd = arcpy.CreateScratchName(
    service
   ,".sd"
   ,None
   ,arcpy.env.scratchFolder
);

arcpy.AddMessage("  SD draft = " + sddraft);
arcpy.AddMessage("  SD  = " + sd);   
   
###############################################################################
#                                                                             #
#  Step 140                                                                   #
#  Create service definition draft                                            #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
results = arcpy.mapping.CreateMapSDDraft(
    map_document = mapDoc
   ,out_sddraft = sddraft
   ,service_name = service
   ,server_type = 'ARCGIS_SERVER'
   ,copy_data_to_server = False
   ,folder_name = ags_folder
   ,summary = ags_summary
   ,tags = ags_tags
);

if results['errors'] != {}:
   arcpy.AddMessage(results['errors']);
   sys.exit();
   
arcpy.AddMessage("  SDDraft created."); 

###############################################################################
#                                                                             #
#  Step 150                                                                   #
#  Alter Service Definitions                                                  #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");

doc = DOM.parse(sddraft);
for k, v in ags_properties.iteritems():
   doc = srv_property(doc,k,v);
for k, v in ags_services.iteritems():
   doc = soe_enable(doc,k,v);
for k, v in ags_service_props.iteritems():
   doc = soe_property(doc,k,v.keys()[0],v.values()[0]);
f = open(sddraft, 'w');
doc.writexml( f );
f.close();

arcpy.AddMessage("  SDDraft edited."); 

###############################################################################
#                                                                             #
#  Step 160                                                                   #
#  Validate the draft                                                         #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
analysis = arcpy.mapping.AnalyzeForSD(sddraft);

if analysis['errors'] != {}:
   arcpy.AddMessage("  ---- ERRORS ----")
   vars = analysis['errors']
   for ((message, code), layerlist) in vars.iteritems():
      arcpy.AddMessage("    " + message + " (CODE " + str(code) + ")");
      if len(layerlist) > 0:
         arcpy.AddMessage("    applies to:");
         for layer in layerlist:
            arcpy.AddMessage("      " + layer.name);
         
   exit(-2);
   
if analysis['warnings'] != {}:
   arcpy.AddMessage("  ---- WARNINGS ----");
   vars = analysis['warnings']
   for ((message, code), layerlist) in vars.iteritems():
      arcpy.AddMessage("    " + message + " (CODE " + str(code) + ")");
      if len(layerlist) > 0:
         arcpy.AddMessage("    applies to:");
         for layer in layerlist:
            arcpy.AddMessage("      " + layer.name);
         
if analysis['messages'] != {}:
   arcpy.AddMessage("  ---- MESSAGES ----");
   vars = analysis['messages']
   for ((message, code), layerlist) in vars.iteritems():
      arcpy.AddMessage("    " + message + " (CODE " + str(code) + ")");
      if len(layerlist) > 0:
         arcpy.AddMessage("    applies to:");
         for layer in layerlist:
            arcpy.AddMessage("      " + layer.name);

if  analysis['messages'] == {}   \
and analysis['warnings'] == {}   \
and analysis['errors'] == {}:
   arcpy.AddMessage("  SD analysis is good.");

###############################################################################
#                                                                             #
#  Step 170                                                                   #
#  Compile the the SDDraft into SD file                                       #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Building SD file from draft...");

arcpy.StageService_server(
    sddraft
   ,sd
);
   
arcpy.AddMessage("    DONE");

###############################################################################
#                                                                             #
#  Step 180                                                                   #
#  Publish the draft to server                                                #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Uploading SD File to AGS...");  
class Callable:
   def __init__(self, anycallable):
      self.__call__ = anycallable

doseq = 1
class MultipartPostHandler(urllib2.BaseHandler):
   handler_order = urllib2.HTTPHandler.handler_order - 10 # needs to run first

   def http_request(self, request):
      data = request.get_data()
      if data is not None and type(data) != str:
         v_files = []
         v_vars = []
         try:
            for(key, value) in data.items():
               if type(value) == file:
                  v_files.append((key, value))
               else:
                  v_vars.append((key, value))
         except TypeError:
            systype, value, traceback = sys.exc_info()
            raise TypeError, "not a valid non-string sequence or mapping object", traceback

         if len(v_files) == 0:
            data = urllib.urlencode(v_vars, doseq)
         else:
            boundary, data = self.multipart_encode(v_vars, v_files)

            contenttype = 'multipart/form-data; boundary=%s' % boundary
            if(request.has_header('Content-Type')
            and request.get_header('Content-Type').find('multipart/form-data') != 0):
               print "Replacing %s with %s" % (request.get_header('content-type'), 'multipart/form-data')
            
            request.add_unredirected_header('Content-Type', contenttype)

         request.add_data(data)
        
      return request

   def multipart_encode(vars, files, boundary = None, buf = None):
      if boundary is None:
         boundary = mimetools.choose_boundary()
      if buf is None:
         buf = StringIO()
      for(key, value) in vars:
         buf.write('--%s\r\n' % boundary)
         buf.write('Content-Disposition: form-data; name="%s"' % key)
         buf.write('\r\n\r\n' + value + '\r\n')
      for(key, fd) in files:
         file_size = os.fstat(fd.fileno())[stat.ST_SIZE]
         filename = fd.name.split('/')[-1]
         contenttype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
         buf.write('--%s\r\n' % boundary)
         buf.write('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (key, filename))
         buf.write('Content-Type: %s\r\n' % contenttype)
         # buffer += 'Content-Length: %s\r\n' % file_size
         fd.seek(0)
         buf.write('\r\n' + fd.read() + '\r\n')
      buf.write('--' + boundary + '--\r\n\r\n')
      buf = buf.getvalue()
      return boundary, buf
      
   multipart_encode = Callable(multipart_encode)

   https_request = http_request   

opener = urllib2.build_opener(MultipartPostHandler);
url = "http://" + ags_server + ":" + ags_port + "/arcgis/admin/uploads/upload?token=" + token;

params = { 
    "description":"SD file uploaded by deployment script"
   ,"f":"json"
   ,"itemFile":open(sd,"rb") 
};

resp_text = opener.open(url.encode('utf-8'), params).read();
response = json.loads(resp_text);

if response["status"] \
and response["status"] == "success":
   upload_item_id = response["item"]["itemID"];
   arcpy.AddMessage("    DONE.");
else:
   arcpy.AddMessage("    ERROR. Upload failed");
   exit(-2);   
   
###############################################################################
#                                                                             #
#  Step 190                                                                   #
#  Harvest the details from the uploaded SD file                              #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Harvesting details from the uploaded SD file...");

sd_info = fetchJson(
    ags_server = ags_server
   ,ags_port   = ags_port
   ,token      = token
   ,serviceURL = "/arcgis/admin/uploads/" + upload_item_id + "/serviceconfiguration.json"
);

if debug:
   with open('sdinfo.json', 'w') as fobj:
      json.dump(sd_info,fobj,sort_keys=True,indent=4,separators=(',', ': '));
      
if sd_info is not None  \
and sd_info["service"] \
and "serviceName" in sd_info["service"]:
   arcpy.AddMessage("    DONE.");
else:
   arcpy.AddMessage("    ERROR unable to query uploaded SD file.");
   exit(-3);

###############################################################################
#                                                                             #
#  Step 200                                                                   #
#  Gather the basic info from the Publishing Server (may not be needed)       #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Gathering basic publishing info from AGS...");

pub_info = fetchJson(
    ags_server = ags_server
   ,ags_port   = ags_port
   ,token      = token
   ,serviceURL = "/arcgis/admin/services/System/PublishingTools.GPServer"
);

if debug:
   with open('basics.json', 'w') as fobj:
      json.dump(pub_info,fobj,sort_keys=True,indent=4,separators=(',', ': '));

if pub_info is not None  \
and pub_info["serviceName"]:
   arcpy.AddMessage("    DONE.");
else:
   arcpy.AddMessage("    ERROR unable to query AGS Publishing Tools.");
   exit(-3);
    
###############################################################################
#                                                                             #
#  Step 210                                                                   #
#  Publish the SD file                                                        #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Now publishing the uploaded SD file...");

pub_sd = fetchJson(
    ags_server = ags_server
   ,ags_port   = ags_port
   ,token      = token
   ,serviceURL = "/arcgis/rest/services/System/PublishingTools/GPServer/Publish%20Service%20Definition/submitJob"
   ,addParams  = {
        "in_sdp_id": upload_item_id
       ,"in_config_overwrite": json.dumps(sd_info)
    }
);

if debug:
   with open('submit.json', 'w') as fobj:
      json.dump(pub_sd,fobj,sort_keys=True,indent=4,separators=(',', ': '));

if pub_sd is not None  \
and pub_sd["jobId"]  \
and pub_sd["jobStatus"] == "esriJobSubmitted":
   job_id = pub_sd["jobId"];
   arcpy.AddMessage("    DONE. (jobID = " + job_id + ")");
else:
   arcpy.AddMessage("    ERROR unable to submit publishing job.");
   exit(-3);
   
###############################################################################
#                                                                             #
#  Step 220                                                                   #
#  Wait for publishing results                                                #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Checking for publishing job results...");

int_counter = 20;
while int_counter > 0:
   pub_check = fetchJson(
       ags_server = ags_server
      ,ags_port   = ags_port
      ,token      = token
      ,serviceURL = "/arcgis/rest/services/System/PublishingTools/GPServer/Publish%20Service%20Definition/jobs/" + job_id
   );
   if debug:
      with open('check.json', 'w') as fobj:
         json.dump(pub_check,fobj,sort_keys=True,indent=4,separators=(',', ': '));

   if pub_check is None  \
   or not "jobStatus" in pub_check:
      arcpy.AddMessage("    ERROR unable to query publishing job status.");
      exit(-3);
      
   if pub_check["jobStatus"] == "esriJobSubmitted":
      arcpy.AddMessage("    esriJobSubmitted...");
      int_counter = int_counter - 1;
      
   elif pub_check["jobStatus"] == "esriJobExecuting":
      arcpy.AddMessage("    esriJobExecuting...");
      int_counter = int_counter - 1;
      
   elif pub_check["jobStatus"] == "esriJobSucceeded":
      arcpy.AddMessage("    esriJobSucceeded...");
      int_counter = 0;
   
   else:
      arcpy.AddMessage("    "  + pub_check["jobStatus"]);
      exit(-3);
      
   time.sleep(5);   
      
###############################################################################
#                                                                             #
#  Step 230                                                                   #
#  Delete the uploaded SD file                                                #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Delete the uploaded SD file from AGS...");

sd_delete = fetchJson(
    ags_server = ags_server
   ,ags_port   = ags_port
   ,token      = token
   ,serviceURL = "/arcgis/admin/uploads/" + upload_item_id + "/delete"
);
if sd_delete is not None   \
and sd_delete["status"]   \
and sd_delete["status"] == "success":
   arcpy.AddMessage("    DONE.");
else:
   arcpy.AddMessage("    ERROR unable to delete SD file.  But continuing...");

###############################################################################
#                                                                             #
#  Step 240                                                                   #
#  Clean up python items                                                      #
#                                                                             #
###############################################################################
arcpy.AddMessage(" ");
arcpy.AddMessage("  Publishing Task Successful.");
del mapDoc, sd, con_ags, con_sde, results, doc;
arcpy.Delete_management(tempMap);

