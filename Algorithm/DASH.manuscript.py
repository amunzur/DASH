from __future__ import division

import os
import math
import pysam
import argparse
import pickle
import subprocess
import numpy as np
import pandas as pd
from Bio import SeqIO
from Bio import pairwise2
import matplotlib
import sys
matplotlib.use('agg')
import matplotlib.pyplot as plt
import seaborn as sns
import re

# Constants
chrom = 'chr6'
contig = '6'
boundary = 10000
# hg19 coordinates
# A_start, A_end = 29910247, 29913661
# B_start, B_end = 31321649, 31324989 
# C_start, C_end = 31236526, 31239913
# hg38 coordinates
A_start,A_end = 29941878, 29946512
B_start,B_end = 31353204, 31357838
C_start,C_end = 31268097, 31272731

min_normal_depth = 15
percentage_mapped = 0.8
bin_size = 150

# Establishing cutoffs
cutoff = 0.5
BAF_cutoff = 0.02
R_cutoff = 0.98

# Get and process the HLA types
def get_HLA_types(path_polysolver_winners, hla_database):
    # Open the polysolver output and format
    with open(path_polysolver_winners, 'r') as input_file:
        lines = input_file.readlines()

    hla_types = []
    for line in lines:
        hla_types.extend(line.split()[1:]) # Split each line by whitespace and append the HLA types to the list

    # Get polysolver alleles
    all_alleles = []
    with open(hla_database, "r") as handle:
        for record in SeqIO.parse(handle, "fasta"):
            all_alleles.append(record.description)

    # Check for existence of HLA types
    for hla in hla_types:
        if hla not in all_alleles:
            hla = get_adjacent_alleles_in_polysolver_dataset(hla, all_alleles)
            if hla not in all_alleles:
                print("[Error] HLA type is not in database. Check format or allele: {0}".format(hla_types))
                sys.exit()

    # Make into dictionaries
    allele_dict = {'A': hla_types[:2],
                      'B': hla_types[2:4],
                      'C': hla_types[4:]}

    return hla_types, allele_dict


# Convert alleles that don't exist in polysolver
def get_adjacent_alleles_in_polysolver_dataset(allele, polysolver_alleles):

    # Check if a digit needs to be removed
    if len([x for x in polysolver_alleles if '_'.join(allele.split('_')[:-1]) == x]) > 0:
        return [x for x in polysolver_alleles if '_'.join(allele.split('_')[:-1]) == x][0]

    # Check if a digit needs to be added (default to taking the first option)
    elif len([x for x in polysolver_alleles if '_'.join(x.split('_')[:-1]) == allele]) > 0:
        return [x for x in polysolver_alleles if '_'.join(x.split('_')[:-1]) == allele][0]

    # Check if two digits need to be removed
    elif len([x for x in polysolver_alleles if '_'.join(allele.split('_')[:-2]) == x]) > 0:
        return [x for x in polysolver_alleles if '_'.join(allele.split('_')[:-2]) == x][0]

    # Check if three digits need to be removed
    elif len([x for x in polysolver_alleles if '_'.join(allele.split('_')[:-3]) == x]) > 0:
        return [x for x in polysolver_alleles if '_'.join(allele.split('_')[:-3]) == x][0]

    # Check if there is a matching super type
    elif len([x for x in polysolver_alleles if '_'.join(allele.split('_')[:3]) in x]) > 0:
        return [x for x in polysolver_alleles if '_'.join(allele.split('_')[:3]) in x][0]

    # No call because there is no allele with the same super type
    else:
        print("No allele with the same super type available.")
        return '-'

def get_mutated_alleles(hla_somatic_mutations):
    '''
    Given a directory containig mutations called by Polysolver, this function reads these files and returns the number of mutations called.
    $indiv.mutect.filtered.nonsyn.annotated -  list of cleaned non-synonymous mutations
    $indiv.mutect.filtered.syn.annotated - list of cleaned synonymous changes
    $indiv.strelka_indels.filtered.annotated
    '''
    # Get a list of all files in the directory
    if os.path.isdir(hla_somatic_mutations):
        files = os.listdir(hla_somatic_mutations)
        search_string = "mutect.filtered.nonsyn.annotated|mutect.filtered.syn.annotated|strelka_indels.filtered.annotated"
        filtered_files = [file for file in files if re.search(search_string, file)]
        mutation_count = 0
        for filename in filtered_files:
            f = pd.read_csv(os.path.join(hla_somatic_mutations, filename), "\t")
            mutation_count += f.shape[0] # up the count by 1 for every mutation identified
        return mutation_count
    else:
        print('Looked for somatic mutations, but no Polysolver file was found.')
        return []

# Run alignment of reads on patient-specific HLA alleles
def run_alignment_on_all_alleles(alleles, normal_dev, tumor_dev, normal_fastq, tumor_fastq):

    # Make fastq for each patient-specific reference allele
    with open(options.all_allele_reference, "r") as handle:
        for record in SeqIO.parse(handle, "fasta"):
            allele_name = record.description
            if allele_name in alleles:
                with open('{0}/{1}.fa'.format(normal_dev, allele_name), 'w') as outfile:
                    outfile.write('>{0}\n'.format(allele_name))
                    outfile.write('{0}'.format(record.seq))
                    print(allele_name, len(record.seq))

    # Run alignments
    for allele in alleles:
        if allele != '-':
            # Make index for each patient-specific reference allele
            subprocess.call(["bwa" ,"index", "-p", '{0}/{1}'.format(normal_dev, allele),
                             '{0}/{1}.fa'.format(normal_dev, allele)])

            # Alignment of each allele with normal reads
            p1 = subprocess.Popen(["bwa", "mem", '{0}/{1}'.format(normal_dev, allele),
                                   normal_fastq], stdout=subprocess.PIPE)
            p2 = subprocess.Popen(["samtools", "sort", "-o",
                                   '{0}/{1}.bam'.format(normal_dev, allele)], stdin=p1.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            p1.stdout.close()
            p2.communicate()

            # Alignment of each allele with tumor reads
            p1 = subprocess.Popen(["bwa", "mem", '{0}/{1}'.format(normal_dev, allele),
                                   tumor_fastq], stdout=subprocess.PIPE)
            p2 = subprocess.Popen(["samtools", "sort", "-o",
                                   '{0}/{1}.bam'.format(tumor_dev, allele)], stdin=p1.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
            p1.stdout.close()
            p2.communicate()


# Remove poorly aligned reads and chimeric reads (lose about 100 chimeric reads)
def clean_up_reads(normal_dev, tumor_dev, alleles, mutated_alleles):

    # Allow greater stringency across all alleles if there is a somatic mutation in at least one allele
    stringency = 0
    if mutated_alleles > 0:
        stringency += 1

    read_name_dict = {}
    for mode, mode_name in zip([normal_dev, tumor_dev], ['normal', 'tumor']):
        read_name_dict[mode_name] = {}
        for allele in alleles:
            if allele != '-':
                # Create index
                subprocess.call(['samtools', 'index',
                                 '{0}/{1}.bam'.format(mode, allele)])

                # Sort reads
                samfile = pysam.AlignmentFile('{0}/{1}.bam'.format(mode, allele), "rb")
                stringentreads = pysam.AlignmentFile('{0}/{1}.stringent.bam'.format(mode, allele),
                                                     "wb", template=samfile)

                read_names = []
                for read in samfile.fetch():
                    #Restrict to reads with perfect alignment
                    if (read.get_tag('NM') <= stringency) and (read.flag not in [2048, 2064]) \
                            and (dict(read.cigartuples)[0] / len(read.seq) > float(percentage_mapped)):
                        stringentreads.write(read)
                        read_names.append(read.query_name)
                stringentreads.close()
                samfile.close()
                read_name_dict[mode_name][allele] = read_names

                # Create index
                subprocess.call(['samtools', 'index',
                                 '{0}/{1}.stringent.bam'.format(mode, allele)])

    return read_name_dict


# Calculate coverage over alleles
def calculate_coverage(normal_dev, tumor_dev, allele_dict):
    allele_coverage_dict = {}
    for mode, mode_name in zip([normal_dev, tumor_dev], ['normal', 'tumor']):
        allele_coverage_dict[mode_name] = {}
        for gene in ['A', 'B', 'C']:

            allele_coverage_dict[mode_name][gene] = {}
            for allele in allele_dict[gene]:
                if allele != '-':

                    all_lines = []
                    subprocess.call(['samtools', 'depth', '-aa',
                                     '{0}/{1}.stringent.bam'.format(mode, allele)],
                                    stdout=open('{0}/{1}.stringent.depth'.format(mode, allele), 'w'))
                    for x in open('{0}/{1}.stringent.depth'.format(mode, allele)).readlines():
                        all_lines.append(x.split('\t'))

                    df = pd.DataFrame(all_lines)[[2]]
                    df.columns = ['Coverage']
                    df.Coverage = df.Coverage.astype('float')

                    allele_coverage_dict[mode_name][gene][allele] = df

    return allele_coverage_dict


# Allow homozygous alleles without breaking output
def address_homozygosity(dash_output_dict, purity, ploidy):

    dash_output_dict['Alleles'].extend([allele1, allele2])
    dash_output_dict['Adjusted_BAF'].extend(['-', '-'])
    dash_output_dict['AS_Coverage'].extend(['-', '-'])
    dash_output_dict['DASH_deletion'].extend([False, False])
    dash_output_dict['Purities'].extend([purity, purity])
    dash_output_dict['Ploidies'].extend([ploidy, ploidy])
    dash_output_dict['Confidence'].extend([-1, -1])
    dash_output_dict['Percentage_Coverage'].extend([0, 0])
    dash_output_dict['Flanking_region_LOH'].extend(['-', '-'])
    dash_output_dict['Total_Coverage'].extend(['-', '-'])
    dash_output_dict['Secondary_check'].extend(['-', '-'])

    print('Alleles are homozygous or non-existent - stopping calculations.')

    return dash_output_dict


# Get alignment from allele names
def get_alignment_of_homologous_alleles(allele1, allele2, hla_database):
    # Get sequences of patient-specific alleles
    with open(hla_database, "r") as handle:
        for record in SeqIO.parse(handle, "fasta"):
            allele_name = record.description
            if allele_name == allele1:
                seq1 = record.seq
            if allele_name == allele2:
                seq2 = record.seq

    # Get alignment of sequences
    alignments = pairwise2.align.globalms(seq1, seq2, 2, -1, -4, -2)  # Identical, Non-identical, Open gap, Extend gap
    return alignments


# Create coverage dataframe and calculate logR
def calculate_logr(gene, allele1, allele2, bin_size, normalization_factor):
    # Get dataframes with coverage across each position
    # Could add a psuedo count here to avoid all weird edge cases
    all_positions_df = pd.DataFrame({'coverage_normal_1': allele_coverage_dict['normal'][gene][allele1].Coverage})
    all_positions_df['coverage_normal_2'] = allele_coverage_dict['normal'][gene][allele2].Coverage
    all_positions_df['coverage_tumor_1'] = allele_coverage_dict['tumor'][gene][allele1].Coverage
    all_positions_df['coverage_tumor_2'] = allele_coverage_dict['tumor'][gene][allele2].Coverage
    all_positions_df['logR'] = 0
    # Added to avoid ensure that is a positive value for every position
    all_positions_df = all_positions_df.replace(np.nan, 0)
    all_positions_df = all_positions_df + 0.01
    #all_positions_df.to_csv('{0}/DASH.all_positions_{1}.tmp.csv'.format(output_dir, gene), index=False)

    for i in range(int(len(all_positions_df) / bin_size) + 1):
        start, end = i * bin_size, (i + 1) * bin_size - 1  # needed because loc adds an extra row compared to iloc
        logR = math.log((all_positions_df.loc[start:end, ["coverage_tumor_1", "coverage_tumor_2"]].mean().sum() /
                         all_positions_df.loc[start:end, ["coverage_normal_1", "coverage_normal_2"]].mean().sum()) * normalization_factor,
                        2)
        all_positions_df.loc[start:end, 'logR'] = logR

    return all_positions_df


# Get mismatch positions and coverage
def get_mismatch_positions(alignments, allele_coverage_dict):
    # Get indices of mismatches in alignment
    mismatches = []
    position, last_indel = 0, -2
    for x, y in zip(alignments[0][0], alignments[0][1]):
        if x == '-' or y == '-':
            if last_indel == position - 1:
                last_indel = position
            else:
                mismatches.append(position)
                last_indel = position
        elif x != y:
            mismatches.append(position)
        position += 1

    # Get the indices of mismatches each sequence
    mismatches_seq1, mismatches_seq2 = [], []  # will produce duplicates over multi-indels
    for mis, seq in zip([mismatches_seq1, mismatches_seq2], [0, 1]):
        position = 0
        for i, x in enumerate(alignments[0][seq]):
            if i in mismatches:
                mis.append(position)
            if x in ['A', 'C', 'G', 'T']:
                position += 1

    df = pd.DataFrame({'Alignment_mismatch': mismatches,
                       'Mismatch_positions_1': mismatches_seq1,
                       'Mismatch_positions_2': mismatches_seq2})

    # Need to also do this while counting each read only once - may need to rename pairs to differentiate
    df['coverage_tumor_1'] = list(allele_coverage_dict['tumor'][gene][allele1].Coverage.iloc[df.Mismatch_positions_1])
    df['coverage_tumor_2'] = list(allele_coverage_dict['tumor'][gene][allele2].Coverage.iloc[df.Mismatch_positions_2])
    df['coverage_normal_1'] = list(allele_coverage_dict['normal'][gene][allele1].Coverage.iloc[df.Mismatch_positions_1])
    df['coverage_normal_2'] = list(allele_coverage_dict['normal'][gene][allele2].Coverage.iloc[df.Mismatch_positions_2])

    df = df.replace(np.nan, 0)
    df = df + 0.01
    return df


def get_percent_coverage(median_cn_per_bin_1, median_cn_per_bin_2):
    a1lowerCov, a2lowerCov = [], []
    for x, y in zip(median_cn_per_bin_1, median_cn_per_bin_2):
        a1lowerCov.append(get_lower_value(x, y))
        a2lowerCov.append(get_lower_value(y, x))

    percCov = np.max([np.mean(a1lowerCov), np.mean(a2lowerCov)])
    print(np.mean(a1lowerCov))
    print(np.mean(a2lowerCov))
    return percCov


# Calculate percentage coverage
def get_lower_value(x, y):
    if math.isnan(x):
        return 0.5
    elif x < y:
        return 0
    else:
        return 1


def plot_results(df, all_positions_df, gene, sample_name, allele1, allele2):
    plt.figure(figsize=(10, 7))
    plt.subplot(4, 1, 1)
    all_positions_df.coverage_normal_1.plot()
    all_positions_df.coverage_normal_2.plot()
    plt.legend(['{0}'.format(allele1), '{0}'.format(allele2)])
    plt.xlim(0, len(all_positions_df))
    plt.ylabel('Normal\nCoverage')
    plt.title('{0} - Gene: {1}'.format(sample_name, gene))

    for mismatch in df.Mismatch_positions_1:
        plt.axvline(mismatch, color='k', alpha=0.2)

    plt.subplot(4, 1, 2)
    all_positions_df.coverage_tumor_1.plot()
    all_positions_df.coverage_tumor_2.plot()
    plt.legend(['{0}'.format(allele1), '{0}'.format(allele2)])
    plt.xlim(0, len(all_positions_df))
    plt.ylabel('Tumor\nCoverage')

    for mismatch in df.Mismatch_positions_1:
        plt.axvline(mismatch, color='k', alpha=0.2)

    plt.subplot(4, 1, 3)

    plt.scatter(df.Mismatch_positions_1, df.BAF, color='black')
    plt.scatter(df.Mismatch_positions_1, df.BAF_normal, color='darkgrey')
    plt.legend(['Tumor', 'Normal'])
    plt.axhline(0.5, color='grey', linestyle='--')
    plt.xlim(0, len(all_positions_df))
    plt.ylim(0, 1)
    plt.ylabel('B-Allele\nFrequency (BAF)')

    plt.subplot(4, 1, 4)
    plt.scatter(df.Alignment_mismatch, df.R1, color=sns.color_palette()[0])
    plt.scatter(df.Alignment_mismatch, df.R2, color=sns.color_palette()[1])
    plt.legend(['{0}'.format(allele1), '{0}'.format(allele2)])
    plt.axhline(1, color='grey', linestyle='--')
    plt.xlim(0, len(all_positions_df))
    plt.ylim(0, 3)
    plt.ylabel('Tumor/Normal\nCoverage Ratio\n(R)')
    plt.xlabel('Genomic position')

    plt.savefig('{0}/coverage_{1}.pdf'.format(output_dir, gene))

# The following is for checking if there is an LOH event in the regions flanking the HLA alleles using the segments.txt file from Sequenza.
def get_sequenza_flanking(dir_sequenza):
    # find the relevant segments.txt in the Sequenza output dirs with the copy number events
    if not any(file.endswith("segments.txt") for file in os.listdir(dir_sequenza)):
        print("Are you sure you ran Sequenza? alternative_solutions.txt file can't be found.")
    else: 
        for file in os.listdir(dir_sequenza):
            if file.endswith('segments.txt'):
                sequenza_cnv_path = os.path.join(dir_sequenza, file)
    # initialize
    sequenza_majors, sequenza_minors = [], []
    sequenza = get_sequenza_all(sequenza_cnv_path)
    for gene in ['A_loss', 'B_loss', 'C_loss']:
        if len(sequenza[sequenza[gene]]) > 0:
            sequenza_majors.extend([list(sequenza[sequenza[gene]].A)[0], list(sequenza[sequenza[gene]].A)[0]])
            sequenza_minors.extend([list(sequenza[sequenza[gene]].B)[0], list(sequenza[sequenza[gene]].B)[0]])
        else:
            sequenza_majors.extend([1, 1])
            sequenza_minors.extend([1, 1])
    # Based on the copy number status, determine if there could be a LOH event. The sum of minor and major will be less than 4 if there is a possible LOH event.
    flanking_loh = []
    result = [a + b for a, b in zip(sequenza_majors, sequenza_minors)]
    for i in range(0, len(result), 2):
        group = result[i:i+2]
        if (sum(group) < 8): 
            flanking_loh.extend(["1"])
        else: 
            flanking_loh.extend(["0"])
    return(",".join(flanking_loh))

# Getting more information out of Sequenza
def get_sequenza_all(sequenza_cnv):
    sequenza = pd.read_csv(sequenza_cnv, sep='\t')
    sequenza = sequenza[sequenza.chromosome.apply(str) == chrom]
 
    sequenza['A_loss'] = sequenza[['start.pos', 'end.pos']].apply(loh_around_hla_a, axis=1)
    sequenza['B_loss'] = sequenza[['start.pos', 'end.pos']].apply(loh_around_hla_b, axis=1)
    sequenza['C_loss'] = sequenza[['start.pos', 'end.pos']].apply(loh_around_hla_c, axis=1)
 
    return sequenza[((sequenza.A_loss)|(sequenza.B_loss)|(sequenza.C_loss))] 
  
# Helper functions
def find_loss(gene_start, gene_end, x):
    start = x[0]
    end = x[1]
    loss = False
 
    # Within the gene region
    if start < gene_end and end > gene_start:
        loss = True
 
    # Before the gene region 
    if start < gene_start and end > gene_start - boundary:
        loss = True
 
    # After the gene region 
    if start < gene_end + boundary and end > gene_end:
        loss = True
    return loss
 
 
def loh_around_hla_a(x):
    gene_start, gene_end = A_start, A_end
    return find_loss(gene_start, gene_end, x)
 
 
def loh_around_hla_b(x):
    gene_start, gene_end = B_start, B_end
    return find_loss(gene_start, gene_end, x)
 
 
def loh_around_hla_c(x):
    gene_start, gene_end = C_start, C_end
    return find_loss(gene_start, gene_end, x)

# Using the alternative_solutions.txt file get the sample ploidy. The first reported solution is used.
def get_ploidy(dir_sequenza): 
    # if there are no files that end with "alternative_solutions.txt":
    if not any(file.endswith("alternative_solutions.txt") for file in os.listdir(dir_sequenza)):
        print("Are you sure you ran Sequenza? alternative_solutions.txt file can't be found.")
    else: 
        for file in os.listdir(dir_sequenza):
            if file.endswith('alternative_solutions.txt'):
                sln = pd.read_csv(os.path.join(dir_sequenza, file), sep='\t')
                ploidy = str(sln.iloc[0]["ploidy"])
                purity = str(sln.iloc[0]["cellularity"])
                return([ploidy, purity])

def get_read_counts(read_counts_path): 
    if os.path.isfile(read_counts_path): 
        with open(read_counts_path) as file:
            counts = file.readlines()
            return(counts[0])
    else: 
        print("Read counts haven't been computed.")
        sys.exit()


if __name__ == "__main__":
    print("Entering Deletion of Allele Specific HLA (DASH) script")

    args = argparse.ArgumentParser()
    # File based inputs
    args.add_argument("--dir_sequenza", action="store", required=True, help="The directory where Sequenza outputs are found.")
    args.add_argument("--path_polysolver_winners", action="store", required=True, help="The path to the winner HLA alleles outputted by Polysolver.")
    args.add_argument("--normal_fastq", action="store", required=True, help="Fastqs with normal HLA reads.")
    args.add_argument("--tumor_fastq", action="store", required=True, help="Fastqs with tumor HLA reads.")
    args.add_argument("--hla_somatic_mutations", action="store", required=True,
                      help="Polysolver HLA somatic calls output file.")
    args.add_argument("--normal_read_count", action="store", required=True,
                      help="Number of reads in the normal.")
    args.add_argument("--tumor_read_count", action="store", required=True,
                      help="Number of reads in the tumor.")
    args.add_argument("--all_allele_reference", action="store", required=True, help="IMGT allele reference file.")
    args.add_argument("--model_filename", action="store", required=True, help="XGBoost model (pickle).")
    args.add_argument("--output_dir", action="store", required=True, help='directory for output information')


    options = args.parse_args()
    print("Arguments parsed.")

    # Making working directories
    output_dir = options.output_dir
    normal_dev = '{0}/normal'.format(output_dir)
    tumor_dev = '{0}/tumor'.format(output_dir)
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
        os.mkdir(normal_dev)
        os.mkdir(tumor_dev)
    else:
        print('[Error] Output directory already exists.')
        sys.exit()
    print("Working directories created.")

    # Save options in run directory
    with open('{0}/params.txt'.format(output_dir), 'w') as outfile:
        for arg in vars(args):
            paramName, paramValue = arg, getattr(args, arg)
            outfile.write('{0}=={1}\n'.format(paramName, paramValue))
    print("Parameters saved for future reference.")

    # Setting model
    model = pickle.load(open(options.model_filename, "rb"))
    print("Model imported.")

    # Get ploidy and purity estimates from Sequenza
    [ploidy, purity] = get_ploidy(options.dir_sequenza)

    # Get the normal and tumor read counts
    normal_read_count = options.normal_read_count
    tumor_read_count = options.tumor_read_count

    # Get flanking regions and convert to integers
    flanking_calls = get_sequenza_flanking(options.dir_sequenza)
    flanking_calls = [int(x) for x in flanking_calls.split(',')]
    print("Flanking calls computed.")

    # Get HLA types
    alleles, allele_dict = get_HLA_types(options.path_polysolver_winners, options.all_allele_reference)
    print("HLA types extracted and formatted.")

    # Get the somatically mutated HLA alleles from Polysolver
    mutated_alleles = get_mutated_alleles(options.hla_somatic_mutations)

    # Run alignment
    run_alignment_on_all_alleles(alleles, normal_dev, tumor_dev,
                                 options.normal_fastq, options.tumor_fastq)
    print("Alignments completed.")

    # Remove poorly aligned reads and chimeric reads (lose about 100 chimeric reads)
    read_name_dict = clean_up_reads(normal_dev, tumor_dev, alleles, mutated_alleles)
    print("Alignments processed.")

    # Calculate coverage over each allele
    allele_coverage_dict = calculate_coverage(normal_dev, tumor_dev, allele_dict)
    print ("Coverage calculated.")

    # Iterate through genes to make predictions
    dash_output_dict = {'Alleles':[], 'Confidence': [], 'Adjusted_BAF': [], 'AS_Coverage': [],
                        'Purities': [], 'Ploidies': [], 'DASH_deletion': [], 'Percentage_Coverage': [],
                        'Flanking_region_LOH': [], 'Total_Coverage': [], 'Secondary_check': []}
    for gene_index, gene in enumerate(['A', 'B', 'C']):
        allele1 = allele_dict[gene][0]
        allele2 = allele_dict[gene][1]
        print("Starting HLA-{0}.".format(gene))

        # Check for homozygous alleles
        if allele1 == allele2:  # Homozygous genes
            dash_output_dict = address_homozygosity(dash_output_dict, float(purity), int(float(ploidy)))
            continue

        # Alignment
        alignments = get_alignment_of_homologous_alleles(allele1, allele2, options.all_allele_reference)

        # Get tumor-normal normalization factor
        normalization_factor = float(normal_read_count) / float(tumor_read_count)
        print('Normalization factor:', 
              )

        # Get coverage values for all positions and for mismatch positions
        all_positions_df = calculate_logr(gene, allele1, allele2, bin_size, normalization_factor)
        all_positions_df.to_csv('{0}/DASH.all_positions_{1}.txt'.format(output_dir, gene), index=False, sep='\t')

        # Create mismatch dataframe and remove sites with low normal coverage
        mismatches_df = get_mismatch_positions(alignments, allele_coverage_dict)
        mismatches_df = mismatches_df[~((mismatches_df.coverage_normal_1 <
                   int(min_normal_depth)) | (mismatches_df.coverage_normal_2 < int(min_normal_depth)))]
        mismatches_df['normalization_factor'] = normalization_factor  # Saving M to review in the output

        # Check for genes that are too close to homozygous to calculate effectively
        print('Number of mismatches: {0}'.format(len(mismatches_df)))
        if len(mismatches_df) < 5:
            print('WARNING: Dangerously low number of mismatches with coverage')
            dash_output_dict = address_homozygosity(dash_output_dict, float(purity), int(float(ploidy)))
            continue

        # Adding non-alignment dependent features
        dash_output_dict['Flanking_region_LOH'].extend([flanking_calls[gene_index], flanking_calls[gene_index]])
        dash_output_dict['Purities'].extend([float(purity), float(purity)])
        dash_output_dict['Ploidies'].extend([int(float(ploidy)), int(float(ploidy))])
        dash_output_dict['Alleles'].extend([allele1, allele2])

        # Calculate the b-allele frequency for each mismatch
        mismatches_df['BAF'] = mismatches_df['coverage_tumor_1'] / (mismatches_df['coverage_tumor_1'] + mismatches_df['coverage_tumor_2'])
        mismatches_df['BAF_normal'] = mismatches_df['coverage_normal_1'] / (mismatches_df['coverage_normal_1'] + mismatches_df['coverage_normal_2'])
        mismatches_df['BAF_loh'] = mismatches_df.BAF - mismatches_df.BAF_normal

        # Calculate allele specific coverage ratios at each mismatch position
        mismatches_df['R1_raw'] = mismatches_df['coverage_tumor_1'] / mismatches_df['coverage_normal_1']
        mismatches_df['R2_raw'] = mismatches_df['coverage_tumor_2'] / mismatches_df['coverage_normal_2']
        mismatches_df['R1'] = mismatches_df['R1_raw'] * normalization_factor
        mismatches_df['R2'] = mismatches_df['R2_raw'] * normalization_factor
        mismatches_df = mismatches_df.replace(np.nan, 0)
        mismatches_df.to_csv('{0}/DASH.mismatches_{1}.txt'.format(output_dir, gene), index=False, sep='\t')

        # Get median adjusted BAF and allele-specific coverage ratio values for each bin
        median_baf_per_bin, median_cov_per_bin_1, median_cov_per_bin_2, median_total_coverage_per_bin = [], [], [], []
        for i in range(int(len(all_positions_df) / bin_size) + 1):
            start, end = i * bin_size, (i + 1) * bin_size
            restricted = mismatches_df[
                (mismatches_df.Mismatch_positions_1 >= start) & (mismatches_df.Mismatch_positions_1 < end)]
            median_baf_per_bin.append(restricted.BAF_loh.median())
            median_cov_per_bin_1.append(restricted.R1.median())
            median_cov_per_bin_2.append(restricted.R2.median())
            median_total_coverage_per_bin.append(restricted.R1.median() + restricted.R2.median())

        # Final alignment features
        coverage_ratio_a1 = np.median(pd.Series(median_cov_per_bin_1).dropna())
        coverage_ratio_a2 = np.median(pd.Series(median_cov_per_bin_2).dropna())
        min_allele_specific_coverage = np.min([coverage_ratio_a1, coverage_ratio_a2])
        total_coverage = np.median(pd.Series(median_total_coverage_per_bin).dropna())
        adj_baf = abs(np.median(pd.Series(median_baf_per_bin).dropna()))
        percCov = get_percent_coverage(median_cov_per_bin_1, median_cov_per_bin_2)
        allele1_quantile_coverage = pd.Series(median_cov_per_bin_1).dropna().quantile(.25)
        allele2_quantile_coverage = pd.Series(median_cov_per_bin_2).dropna().quantile(.25)

        # Update output dictionary
        dash_output_dict['Adjusted_BAF'].extend([adj_baf, adj_baf])
        dash_output_dict['AS_Coverage'].extend([coverage_ratio_a1, coverage_ratio_a2])
        dash_output_dict['Percentage_Coverage'].extend([percCov, percCov])
        dash_output_dict['Total_Coverage'].extend([total_coverage, total_coverage])

        # Machine learning prediction
        prediction_df = pd.DataFrame({'purity': [float(purity)], 'ploidy': [int(float(ploidy))],
                                      'Sequenza_Loss': [flanking_calls[gene_index]],
                                      'minMedCoverage': [min_allele_specific_coverage], 'baf_median': [adj_baf],
                                      'percCov': [percCov], 'totalCoverage_median': [total_coverage]})

        prediction_df = prediction_df.reindex(columns=['purity', 'ploidy', 'Sequenza_Loss', 'minMedCoverage', 'baf_median', 'percCov', 'totalCoverage_median'])

        # prediction_df = pd.DataFrame({'Sequenza_Loss': [flanking_calls[gene_index]], 'baf_median': [adj_baf], 
        #                               'minMedCoverage': [min_allele_specific_coverage], 'percCov': [percCov], 
        #                               'ploidy': [int(float(ploidy))], 'purity': [float(options.purity)], 
        #                               'totalCoverage_median': [total_coverage]})

        prediction_df.to_csv('{0}/DASH.features_{1}.csv'.format(output_dir, gene), index=False)
        prediction_probability = model.predict_proba(prediction_df)[0][1]

        # Secondary check to increase specificity
        secondary_check = ~((adj_baf > BAF_cutoff) & (min_allele_specific_coverage < R_cutoff))
        print(secondary_check, adj_baf, BAF_cutoff, min_allele_specific_coverage, R_cutoff)

        dash_output_dict['Confidence'].extend([prediction_probability, prediction_probability])
        dash_output_dict['Secondary_check'].extend([secondary_check, secondary_check])

        if secondary_check:
            print('Updating probability.')
            prediction_probability = 0

        # LOH determination
        if prediction_probability < cutoff:
            dash_output_dict['DASH_deletion'].extend([False, False])
        else:
            if (allele1_quantile_coverage < 0.5) & (allele2_quantile_coverage < 0.5):
                 dash_output_dict['DASH_deletion'].extend([True, True])
            elif coverage_ratio_a1 < coverage_ratio_a2:
                dash_output_dict['DASH_deletion'].extend([True, False])
            else:
                dash_output_dict['DASH_deletion'].extend([False, True])

    #print(dash_output_dict)
    output = pd.DataFrame(dash_output_dict)
    output = output[['Alleles', 'DASH_deletion', 'Secondary_check', 'Confidence', 'Flanking_region_LOH', 'Adjusted_BAF',
                     'AS_Coverage', 'Purities', 'Ploidies', 'Percentage_Coverage', 'Total_Coverage']]

    output = output.replace(np.nan, '-')
    output.to_csv('{0}/DASH.output.txt'.format(output_dir), index=False, sep='\t')

    # plotting
    print("Plotting.")
    for gene in ["A", "B", "C"]:
        PATH_df = os.path.join(output_dir, "DASH." + "mismatches_" + gene + ".txt")
        PATH_all_positions_df = os.path.join(output_dir, "DASH." + "all_positions_" + gene + ".txt")
        if os.path.exists(PATH_df) and os.path.exists(PATH_all_positions_df):
            df = pd.read_csv(PATH_df, sep='\t')
            all_positions_df = pd.read_csv(PATH_all_positions_df, sep='\t')
            allele1 = allele_dict[gene][0]
            allele2 = allele_dict[gene][1]
            plot_results(df, all_positions_df, gene, "sample_name", allele1, allele2)
        else:
            print("For HLA-", gene, "at least one of the required outputs does not exist. Abort plotting.")
    print('Done.')