#!/usr/bin/env python3
import argparse
import os.path
import json
from check import readPOFiles
try:
    import cffi_re2 as re2
except ImportError:
    import re as re2
import simplejson as json

imageRegex = re2.compile(r"https?://ka-perseus-(images|graphie)\.s3\.amazonaws.com/([a-z0-9]+)\.(jpeg|jpg|png)")
graphieRegex = re2.compile(r"web\+graphie://ka-perseus-graphie\.s3\.amazonaws.com/([a-z0-9]+)")

images = set()
graphie = set()

def findInPO(po):
    for entry in po:
        engl = entry.msgid
        trans = entry.msgstr

        for hit in imageRegex.findall(engl) + imageRegex.findall(trans):
            images.add("{}.{}".format(hit[1], hit[2]))

        for hit in graphieRegex.findall(engl) + graphieRegex.findall(trans):
            graphie.add(hit)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--language', default="de", help='The language to use')
    args = parser.parse_args()

    po = readPOFiles(os.path.join("cache", args.language))
    for pot in po.values():
        findInPO(pot)

    with open(os.path.join("output", args.language, "images.json"), "w") as outfile:
        json.dump(list(images), outfile)

    with open(os.path.join("output", args.language, "graphie.json"), "w") as outfile:
        json.dump(list(graphie), outfile)
