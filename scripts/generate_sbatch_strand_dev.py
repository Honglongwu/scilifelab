#!/usr/bin/env python
import sys
import os
import optparse
import glob
import yaml
import couchdb
from scilifelab.google import *
import bcbio.pipeline.config_loader as cl

usage = """
Generate sbatch files for running an mRNA-seq pipeline.
Usage:

generate_sbatch.py <Flow cell ID, eg 121113_BD1HG4ACXX> <project ID> <Bowtie index for reference genome>
The four first options are mandatory. There are further flags you can use:

-s, --single: if single end
-c, --config: Provide config file (post_process.yaml)
-o, --old: Run old TopHat (1.0.14) instead - mainly to reproduce old runs
-t, --projtag: Provide a project tag that will be shown in the queuing system to distinguish from other TopHat runs
-p, --phred64: Use phred64 quality scale
-f, --fai: Generate UCSC Genome Browser compatible BigWig tracks, using the specified FASTA index (fai) file
-m, --mail: Specify a mailing address for SLURM
-a, --alloc-time: Time to allocate in SLURM. Hours:minutes:seconds or days-hours:minutes:seconds
-w, --fpath: Path to fastq files. If not given, the script assumes the standars structure of the analysis directory. And that you run the script from the intermediate directory.
-r, --stranded: Run stranded version of tophat
"""

if len(sys.argv) < 4:
    sys.exit(usage)

##      Couchdb functions
def find_proj_from_view(proj_db, proj_id):
    view = proj_db.view('project/project_name')
    for proj in view:
        if proj.key == proj_id:
            return proj.value
    return None

def get_size(n,info):
    preps = 'BCDE'
    prep = ''
    name = n.replace('-', '_').replace(' ', '').split("_index")[0].split("_ss")[0].split("_dual")[0].strip().strip('F')
    while name[-1] in preps:
        prep = name[-1] + prep
        name = name[0: -1]
    if prep == '':
            prep = 'A'
    for samp in info['samples']:
        if samp.strip('F')==name.strip('F'):
            try:
                size=info['samples'][samp.strip('F')]['library_prep'][prep]['average_size_bp']
            except:
                key=info['samples'][samp.strip('F')]['library_prep'][prep]['library_validation'].keys()[0]
                size=info['samples'][samp.strip('F')]['library_prep'][prep]['library_validation'][key]['average_size_bp']
        elif name[0]=='P' and name.split('_')[1]==samp:
            print "Best gues for sample found on statusDB corresponding to sample name ",n ," is ",samp
            r = raw_input("If this seems to be correct press y      ")
            if r.upper() == "Y":
                size=info['samples'][samp]['library_prep'][prep]['average_size_bp']
    return int(float(size))


parser = optparse.OptionParser()
parser.add_option('-s', '--single', action="store_true", dest="single", default="False", help="Run tophat with single end reads.")
parser.add_option('-c', '--config', action="store", dest="conffile", default=os.path.expanduser("~/opt/config/post_process.yaml"), help="Specify config file (post_process.yaml)")
parser.add_option('-o', '--old', action="store_true", dest="old", default="False", help="Run old TopHat (1.0.14) instead - mainly to reproduce old runs")
parser.add_option('-t', '--projtag', action="store", dest="projtag", default="", help="Provide a project tag that will be shown in the queuing system to distinguish from other TopHat runs")
parser.add_option('-p', '--phred64', action="store_true", dest="phred64", default="False", help="Use phred64 quality scale")
parser.add_option('-f', '--fai', action="store", dest="fai", default="", help="Provide FASTA index file for generating UCSC bigwig tracks")
parser.add_option('-m', '--mail', action="store", dest="mail", default="mikael.huss@scilifelab.se", help="Specify a mailing address for SLURM mail notifications")
parser.add_option('-a', '--alloc-time', action="store", dest="hours", default="40:00:00", help="Time to allocate in SLURM. Please specify as hours:minutes:seconds or days-hours:minutes:seconds")
parser.add_option('-w', '--fpath', dest="fpath", default=False, help="Path to fastq files. If not given, the script assumes the standars structure of the analysis directory'")
parser.add_option('-r', '--stranded', action="store_true", dest="stranded", default="False", help="Run tophat with --librarytype fr-firststranded option for strand-specific RNAseq.")

(opts, args)    = parser.parse_args()
old             = opts.old
phred64         = opts.phred64
fai             = opts.fai
projtag         = opts.projtag
mail            = opts.mail
hours           = opts.hours
conffile        = opts.conffile
fpath           = opts.fpath
single          = opts.single
print "Single single"

#Settings for stranded/non-stranded analysis
if opts.stranded:
    print "Stranded RNAseq analysis, requires special bowtie index"
    analysis_type='RNA-seq stranded analysis'
    #the name in custom_algorithms section in opt/config/post_process.yaml
else:
    analysis_type='RNA-seq analysis'


proj_ID         = sys.argv[2]
refpath         = sys.argv[3]
conf            = cl.load_config(conffile)

#tophat and cufflinks:
aligner_version         = conf['custom_algorithms'][analysis_type]['aligner_version']  
aligner_libtype         = conf['custom_algorithms'][analysis_type]['aligner_libtype']

port                    = conf['couch_db']['maggie_port']
username                = conf['couch_db']['maggie_login']
password                = conf['couch_db']['maggie_pass']
print username+':'+password+'@'+conf['couch_db']['maggie_url']
URL                     = username+':'+password+'@'+conf['couch_db']['maggie_url']
extra_arg               = "#SBATCH " + conf['sbatch']['extra_arg']
couch                   = couchdb.Server("http://" + URL + ':' +str(port))
proj_db                 = couch['projects']
key                     = find_proj_from_view(proj_db, proj_ID)
print key
info                    = proj_db[key]


if not len ( hours.split(':') ) == 3:
        sys.exit("Please specify the time allocation string as hours:minutes:seconds or days-hours:minutes:seconds")

if phred64 == True:
        qscale = '--solexa1.3-quals'
else:
        qscale = ''

if not fpath:
        p = os.getcwd()
        fpath = p.split('intermediate')[0] + 'data/' + sys.argv[1]
print fpath
p=os.getcwd()

if not os.path.exists(fpath):
        sys.exit('no such dir '+fpath)


flist = glob.glob(str(fpath + '/*'))
file_info={}

for f in flist:
    fname   =       f.split('/')[-1]
    try:
        if (fname.split('.')[-1] == "fastq") | ( fname.split('.')[-2] == "fastq"):
            lane_run        = "_".join(fname.split("_")[0:3])
            tag             = "_".join(fname.split("_")[3:-2])
            if not file_info.has_key(lane_run):
                file_info[lane_run]={}
            if not file_info[lane_run].has_key(tag):
                file_info[lane_run][tag]={}
            if (fname.split('.fastq')[0][-1] == "1"):
                file_info[lane_run][tag]['R1']=fname
            else:
                file_info[lane_run][tag]['R2']=fname
    except:
                sys.exit('files missing? '+fname)
print file_info.keys()

print "Best guess for sample names: "
for lane in file_info:
    print lane
    print sorted(file_info[lane].keys())

r = raw_input("Press n to exit")
if r.upper() == "N": sys.exit(0)



for lane in file_info:
    an_path = p+'/'+lane
    if not os.path.exists(an_path):
        os.mkdir(an_path)

    print an_path
    for samp in sorted(file_info[lane]):
        ## Handeling some anoying options in a ugly way
        if old == True:
            aligner_version = "1.0.14"
            sam_bam="samtools view -bT concat.fa.fa -o accepted_hits_"+samp+".bam accepted_hits.sam"
        else:
            aligner_version = conf['custom_algorithms'][analysis_type]['aligner_version']
        sam_bam="mv accepted_hits.bam accepted_hits_"+samp+".bam"
        if fai != '':
            make_fai="""genomeCoverageBed -bga -split -ibam accepted_hits_sorted_dupRemoved_"""+samp+""".bam -g """+fai+""" > sample_"""+samp+""".bga
"""+ bedGraphToBigWig +""" sample_"""+samp+""".bga"""+fai+""" sample_"""+samp+""".bw"""
        else:
            make_fai=''

        ## trying to get average fragemnt length from couchDB
        if single is True:
            R1 = fpath+'/'+file_info[lane][samp]['R1']
            R2 = ''
            innerdist = ''
            innnerdistflagg = ''
        else:
            R1 = fpath+'/'+file_info[lane][samp]['R1']
            R2 = fpath+'/'+file_info[lane][samp]['R2']
            print R1
            print R2
            innnerdistflagg = '-r'
        try:
            size = get_size(samp,info)
            print "Average fragment length ", str(size)
        except:
            print ""
            size = raw_input("Could not find information on statusDB. Enter manualy fragment size including adapters for sample " + samp + ": ")
            pass
        innerdist = str(int(size) - 101 - 101 - 121)
        size=str(size)
        if not size.isdigit(): sys.exit(0)

        ### Generating sbatch file for sample
        f = open(an_path+"/map_tophat_"+samp+".sh", "w")
        print >>f, """#! /bin/bash -l

#SBATCH -A a2012043
#SBATCH -p node
#SBATCH -t {0}
#SBATCH -J tophat_{1}
#SBATCH -e tophat_{1}.err
#SBATCH -o tophat_{1}.out
#SBATCH --mail-user={2}
#SBATCH --mail-type=ALL
{9}

module unload bioinfo-tools
module unload bowtie
module unload tophat

module load bioinfo-tools
module load samtools
module load tophat/{3}

tophat -o tophat_out_{1} {13} -p 8 {10} {6} {4} {5} {7} {8}
cd tophat_out_{1}
{11}
{12}
""".format(hours ,samp ,mail ,aligner_version,innerdist,refpath,innnerdistflagg,R1,R2,extra_arg, aligner_libtype,sam_bam,make_fai, qscale)
#""".format(hours ,samp ,mail ,aligner_version,quantifyer_version,counts_version,innerdist,refpath,innnerdistflagg,R1,R2,extra_arg, aligner_libtype,sam_bam,make_fai, qscale)
        f.close()
