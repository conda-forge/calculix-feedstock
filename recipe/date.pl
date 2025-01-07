#!/usr/bin/env perl
use strict;
use warnings;

# For a human-readable string like "Wed Jan  1 00:00:00 2025"
my $date = scalar localtime;

# Or, for a custom format, you could use the POSIX strftime approach:
# use POSIX qw(strftime);
# my $date = strftime("%Y-%m-%d %H:%M:%S", localtime);

# Now do your file-editing
@ARGV = ("ccx_$(VERSION).c");
$^I   = ".old";
while (<>) {
    s/You are using an executable made on.*/You are using an executable made on $date\\n");/;
    print;
}

@ARGV = ("ccx_$(VERSION)step.c");
$^I   = ".old";
while (<>) {
    s/You are using an executable made on.*/You are using an executable made on $date\\n");/;
    print;
}

@ARGV = ("frd.c");
$^I   = ".old";
while (<>) {
    s/COMPILETIME.*/COMPILETIME       $date                    \\n\",p1);/;
    print;
}

# Clean up old files
unlink "CalculiX.c.old";
unlink "CalculiXstep.c.old";
unlink "frd.c.old";
