#!/usr/bin/env perl
use strict;
use warnings;

my $version = $ENV{'PKG_VERSION'};

# For a human-readable string like "Wed Jan  1 00:00:00 2025"
my $date = scalar localtime;

# Or, for a custom format, you could use the POSIX strftime approach:
# use POSIX qw(strftime);
# my $date = strftime("%Y-%m-%d %H:%M:%S", localtime);

# Now do your file-editing
@ARGV = ("ccx_$(version).c");
$^I   = ".old";
while (<>) {
    s/You are using an executable made on.*/You are using an executable made on $date\\n");/;
    print;
}

@ARGV = ("ccx_$(version)step.c");
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
unlink "ccx_$(version).c.old";
unlink "ccx_$(version)step.c.old";
unlink "frd.c.old";
