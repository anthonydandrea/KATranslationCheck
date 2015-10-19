#!/usr/bin/env python3
"""
Update files by individually exporting from Crowdin.

This script assumes that a full file tree is already present (e.g. in the "de" directory).
Non-present files will NOT be updated.
"""
import requests
import json
import re
import os
import time
import errno
import os.path
import datetime
from retry import retry
from multiprocessing import Pool
from bs4 import BeautifulSoup
from ansicolor import red, black, blue, green

def translationFilemapCacheFilename(lang="de"):
    return os.path.join("cache", "translation-filemap-{0}.json".format(lang))

def loadUsernamePassword():
    """ """
    with open("crowdin-credentials.json") as infile:
        return json.load(infile)

# Globally load credentials
crowdingCredentials = loadUsernamePassword()

# Perform login
def getCrowdinSession():
    s = requests.Session()
    username = crowdingCredentials["username"]
    password = crowdingCredentials["password"]
    loginData = {"password": password, "submitted": 1, "redirect": "/profile", "email_as_login": "", "login": username}
    response = s.post("http://crowdin.khanacademy.org/login", data=loginData, stream=False)
    return s

@retry(tries=8)
def downloadTranslationFilemap(lang="de"):
    """
    Create a filename -> info map for a given Crowdin.
    The info contains all crowdin info plus the "id" property,
    containing the numeric file ID on Crowdin and the "path" property
    containing the path inside the language directory.
    """
    # Extract filemap
    response = requests.get("http://crowdin.khanacademy.org/project/khanacademy/%s" % lang)
    soup = BeautifulSoup(response.text, "lxml")
    scripttext = soup.find_all("script")[3].text
    jsonStr = scripttext.partition("PROJECT_FILES = ")[2]
    jsonStr = jsonStr.rpartition(", DOWNLOAD_PERMISSIONS")[0].replace("\\/", "/")
    projectFiles = json.loads(jsonStr)
    # Build map for the directory structure
    directoryMap = {
        v["id"]: v["name"] + "/"
        for k, v in projectFiles.items()
        if v["node_type"] == "0"} # 0 -> directory
    # Filter only POT. Create filename -> object map with "id" property set
    idRegex = re.compile("/khanacademy/(\d+)/enus-de")
    return {
        v["name"]: dict(v.items() | [("id", int(v["id"])), ("path", directoryMap[v["parent_id"]] + v["name"])])
        for k, v in projectFiles.items()
        if v["name"].endswith(".pot")}

@retry(tries=8, delay=5.0)
def performPOTDownload(argtuple):
    """
    Explicitly uncurried function that downloads a single Crowdin file
    to a filesystem file. fileid, filepath
    """
    # Extract argument tuple
    fileid, filepath = argtuple
    urlPrefix = "http://crowdin.khanacademy.org/project/khanacademy/de/%s/" % str(fileid)
    # Initialize session
    s = getCrowdinSession()
    # Trigger export
    exportResponse = s.get(urlPrefix + "export", headers={"Accept": "application/json"})
    #print(exportResponse.text)
    if exportResponse.json()["success"] != True:
        raise Exception("Crowdin export failed: " + response.text)
    # Trigger download
    # Store in file
    with open(filepath, "w+b") as outfile:
        response = s.get(urlPrefix + "download", stream=True)

        if not response.ok:
            raise Exception("Download error")

        for block in response.iter_content(1024):
            outfile.write(block)
    print(green("Downloaded %s" % filepath))

def findExistingPOFiles(lang="de", directory="de"):
    """Find PO files which already exist in the language directory"""
    for (curdir, _, files) in os.walk(directory):
        for f in files:
            #Ignore non-PO files
            if not f.endswith(".po"): continue
            #Add to list of files to process
            yield os.path.join(curdir, f)

def updateTranslationFilemapCache(lang="de"):
    """Re-download the translation filemap cache"""
    print(black("Updating translation filemap for {0}".format(lang), bold=True))
    filename = translationFilemapCacheFilename(lang)
    with open(filename, "w") as outfile:
        translation_filemap = downloadTranslationFilemap(lang)
        json.dump(translation_filemap, outfile)
        return translation_filemap

def getTranslationFilemapCache(lang="de",  forceUpdate=False):
    # Enforce update if file does not exist
    filename = translationFilemapCacheFilename(lang)
    if not os.path.isfile(filename) or forceUpdate:
        updateTranslationFilemapCache(lang)
    # Read filename cache
    with open(filename) as infile:
        return json.load(infile)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--language', default="de", help='The language directory to use/extract (e.g. de, es)')
    parser.add_argument('-j', '--num-processes', default=1, type=int, help='Number of processes to use for parallel download')
    parser.add_argument('-d', '--delay', default=0, type=float, help='Delay (in seconds) to sleep between fetches for -j 1')
    parser.add_argument('-f', '--force-filemap-update', action="store_true", help='Force updating the filemap')
    args = parser.parse_args()

    # Get map that contains (besides other stuff)
    #  the crowdin ID for a given file
    translationFilemap = getTranslationFilemapCache(args.language, args.force_filemap_update)

    # Collect valid downloadable files for parallel processing
    fileinfos = []
    for filename, fileinfo in translationFilemap.items():
        filepath = os.path.join("cache", args.language, fileinfo["path"])
        # Create dir if not exists
        try: os.makedirs(os.path.dirname(filepath))
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                pass
            else:
                raise
        fileid = fileinfo["id"]
        fileinfos.append((fileid, filepath))
    # Perform parallel download
    if args.num_processes > 1:
        pool = Pool(args.num_processes)
        pool.map(performPOTDownload, fileinfos)
    else:
        for t in fileinfos:
            performPOTDownload(t)
            time.sleep(args.delay)
    #Set download timestamp
    timestamp = datetime.datetime.now().strftime("%y-%m-%d %H:%M:%S")
    with open("lastdownload.txt", "w") as outfile:
        outfile.write(timestamp)
