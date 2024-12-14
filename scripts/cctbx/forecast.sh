#!/bin/bash
input=$1 # input main log file
res=$2   # input desired resolution

awk '/STEP /{n++}{print > "step" n ".txt"}' $input
n_imgs=`grep Images: step1.txt | awk '{print $3}' | sed 's/,//g'`
awk '/Intensity Statistics/{n++}{print > "stats" n ".txt"}' step11.txt
awk '/------------/{n++}{print > "table" n  ".txt"}' stats3.txt
grep -v "\-1\.0000" table2.txt > tmp1.txt
grep -v "\-\-\-\-\-\-" tmp1.txt > tmp2.txt
grep " \- " tmp2.txt > data.txt
awk -v res="$res" '{ if ($2 >= res && $4 <= res) print $0 }' data.txt > res.txt
multiplicity=`awk '{print $8}' res.txt`
rm -f step*.txt stats*.txt table*.txt tmp*.txt data.txt res.txt
factor=$(echo "scale=2; 10.0 / $multiplicity" | bc)

echo "Need ${factor}X more crystals to reach $res A. Got $n_imgs so far..."
