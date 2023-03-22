
## DASH (Deletion of Allele-specific HLAs)
This repo contains some modifications I made to the source code of the DASH project. The changes are as follows:
1. Originally the plotting function (`plot_results`) wasn't called. My changes run the plotting function for
each gene (A, B and C) and for each allele in each gene. The resulting pdf is outputted to the output directory provided by the user.
Both the `positions` and `all_positions` files need to exist for plotting to work. If one or both are missing, the plotting function won't run.
2. I added a conda yaml file with all dependencies.
3. To make the script compatible with conda, I modified how `sub.process` was called. Now within the conda system
you no longer need to add `samtools` or `bwa` to the path. It only needs to exist within the conda environment.
4. The `prediction_df` needed for the ML step needs to have its columns ordered in a specific way to match the
trained model. Correct order is ensured with the use of `reindex` from `pandas`.
5. Some minor changes throughout the script so that the ploidy estimates are correctly converted to an integer.
We first need to convert it to float, and then to an integer.
6. Instead of supplying the `b_allele_flanking_loh`, now the user just needs to give the path to the `segments.txt` file from Sequenza. The whether there is a LOH event or not is computed in the script. 1 means there is a deletion, 0 means not.
7. It is no longer needed to give the Polysolver output in a string format separated by `*` and `:`. Instead of `hla_types`, the user can give the path to the `winners_hla.txt` file from HLA-Polysolver. The alleles are formatted in the script.

### How to run DASH: 
The new parameters needed are: 
`--purity:` Tumor purity
`--ploidy:` Tumor ploidy
`--path_polysolver_winners:` The path to the `winners_hla.txt` file from HLA-Polysolver
`--normal_fastq:` Fastq with reads from normal sample
`--tumor_fastq:` Fastq with reads from tumor sample
`--hla_somatic_mutations:` HLA somatic mutations (polysolver file)
`--normal_read_count:` Number of reads from normal sample
`--tumor_read_count:` Number of reads from tumor sample
`--sequenza_cnv:` The path to the `segments.txt` file from Sequenza
`--all_allele_reference:` Reference database of genomic sequences for all alleles
`--model_filename:` Model file name (This file needs to be requested from authors. Please send an email to bioinformatics.science@personalis.com.)
`--output_dir:` Output directory

### Here is an example: 
```
python DASH.manuscript.py --purity 0.34 \
						  --ploidy 3.7 \
						  --hla_types /some/path.hla_winners.txt \
						  --normal_fastq ./test_data/HLA_reads.normal.fasta \
						  --tumor_fastq ./test_data/HLA_reads.tumor.fasta \
						  --hla_somatic_mutations ./test_data/hla_mutations.merged.vcf \
						  --normal_read_count 166545259.1184 \
						  --tumor_read_count 333050764.298 \
						  --sequenza_cnv /some/path/sample_segments.txt \
						  --all_allele_reference ./test_data/hla_gen.fasta.IMGTv312.txt \
						  --model_filename some/path/model.p \
						  --output_dir ./test_output
```
