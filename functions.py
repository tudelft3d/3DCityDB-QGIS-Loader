# -*- coding: utf-8 -*-
import os, configparser
import psycopg2
from qgis.core import QgsApplication, TableFlags

class database_cred:
    def __init__(self,connection_name,database): 
        self.connection_name=connection_name
        self.database=database
        self.host=None
        self.port=None
        self.user=None
        self.password='*****'
        self.store_creds=None
        self.is_active=None
        self.id=id(self)
        self.hex_location=hex(self.id)
        

    def __str__(self):
        print(f"connection name: {self.connection_name}") 
        print(f"db name: {self.database}")
        print(f"host:{self.host}")
        print(f"port:{self.port}")
        print(f"user:{self.user}")
        print(f"password:{self.password[0]}{self.password[1]}*****")
        print(f"id:{self.id}")
        print(f"hex location:{self.hex_location}")
        return('\n')
    
    def add_to_collection(self,db_collection):
        db_collection.append(self)
        #print(f"{hex(id(self))} was added to db collection {db_collection}")

def get_postgres_conn(self):
    """ Reads QGIS3.ini to get saved user connection parameters of postgres databases""" 

    #Current active profile directory #TODO: check if path exists #os.path.exists(my_path)
    profile_dir = QgsApplication.qgisSettingsDirPath()
    ini_path=os.path.join(profile_dir,"QGIS","QGIS3.ini")
    ini_path=os.path.normpath(ini_path)

    # Clear the contents of the comboBox from previous runs
    self.btnConnToExist.clear()

    

    parser = configparser.ConfigParser()

    #Makes path 'Case Sensitive'
    parser.optionxform = str 

    parser.read(ini_path)

    db_collection = []
    for key in parser['PostgreSQL']:
        current_connection_name = str(key).split("\\")[1] #NOTE: seems too hardcoded, might break in the feature if .ini structure changes
        
        #Show database and connection name into combobox
        if 'database' in str(key):
            database_cred
            database = parser['PostgreSQL'][key]

            #Create DB instance based on current connection. This IF (and the rest) is visited only once per connection  
            db_instance =database_cred(current_connection_name,database)
            db_instance.add_to_collection(db_collection)

            self.btnConnToExist.addItem(f'{current_connection_name}',db_instance)#hex(id(db_instance)))
            
        if 'host' in str(key):
            host = parser['PostgreSQL'][key]
            db_instance.host=host

        if 'port' in str(key):
            port = parser['PostgreSQL'][key]
            db_instance.port=port

        if 'user' in str(key):
            user = parser['PostgreSQL'][key]
            db_instance.user=user

        if 'password' in str(key): 
            password = parser['PostgreSQL'][key]
            db_instance.password=password
 
    #NOTE: the above implementation works but feels unstable! Test it 

    return db_collection

def connect(db):

    # connect to the PostgreSQL server
    # print('Connecting to the PostgreSQL database...')
    connection = psycopg2.connect(dbname= db.database,
                            user= db.user,
                            password= db.password,
                            host= db.host,
                            port= db.port)
    return connection


def connect_and_check(db):
    """ Connect to the PostgreSQL database server """

    conn = None
    try:

        conn = connect(db)
		
        # create a cursor
        cur = conn.cursor()
        
        # get all tables with theirs schemas    inspired from https://www.codedrome.com/reading-postgresql-database-schemas-with-python/ (access on 27/11/21)
        cur.execute("""SELECT table_schema,table_name
                      FROM information_schema.tables
                      WHERE table_schema != 'pg_catalog'
                      AND table_schema != 'information_schema'
                      AND table_type='BASE TABLE'
                      ORDER BY table_schema,table_name""")
        table_schema = cur.fetchall() #NOTE: For some reason it can't get ALL the schemas

        #Get all schemas
        cur.execute("SELECT schema_name FROM information_schema.schemata")
        schema = cur.fetchall()

	    # # get all tables
        # cur.execute("""SELECT table_name
        #               FROM information_schema.tables
        #               WHERE table_schema != 'pg_catalog'
        #               AND table_schema != 'information_schema'
        #               AND table_type='BASE TABLE'
        #               ORDER BY table_name""")
        # tables = cur.fetchall()


        #Check conditions for a valid the 3DCityDB structure. NOTE: this is an oversimplified test! there are countless conditions where the requirements are met but the structure is broken.
        exists = {'cityobject':False,'building':False,'citydb_pkg':False}
        
        #table check
        for pair in table_schema:
            if 'cityobject' in pair:
                exists['cityobject']=True
            if 'building' in pair:
                exists['building']=True
            if 'citydb_pkg' in pair:
                exists['citydb_pkg']=True
        #chema check
        for pair in schema:
            if 'citydb_pkg' in pair:
                exists['citydb_pkg']=True
        
        if not (exists['cityobject'] and exists['building'] and exists['citydb_pkg']):
            return 0

        


	
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            # close the communication with the PostgreSQL
            cur.close()
            conn.close()
    return 1


def fill_schema_box(self,db):

    conn = None
    try:

        conn = connect(db)

        # create a cursor
        cur = conn.cursor()

        #Get all schemas
        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name != 'information_schema' AND NOT schema_name LIKE '%pg%' ORDER BY schema_name ASC")
        schema = cur.fetchall()

        #schema check
        schemas=[]
        for pair in schema:
            #print(pair[0])
            schemas.append(pair[0])

        self.cbxScema.clear()
        self.cbxScema.addItems(schemas)

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            # close the communication with the PostgreSQL
            cur.close()
            conn.close()
    return 1

def check_schema(self,db,idx):

    conn = None
    try:

        conn = connect(db)

        #Get schema stored in 'schema combobox'
        schema=self.cbxScema.currentText()
    
        #TODO: Check if current schema has cityobject, building features.

        

    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            # close the communication with the PostgreSQL
            #cur.close()
            pass
    return 1



#NOTE:TODO: for every event and every check of database, a new connection Opens/Closes. 
#Maybe find a way to keep the connection open until the plugin ultimately closes