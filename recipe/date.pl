#!/usr/bin/env perl
#
# Stamps the build date into the sources, like upstream's own date.pl.
# Must run before the sources are compiled so that frd.c picks the stamp up
# as well (build.sh/build.bat call it ahead of make).
#
use strict;
use warnings;

my $version = $ENV{'PKG_VERSION'}
    or die "date.pl: PKG_VERSION is not set\n";

my $date = scalar localtime;

sub stamp {
    my ($file, $pattern, $replacement) = @_;
    -f $file or die "date.pl: $file not found\n";
    local @ARGV = ($file);
    local $^I = '.old';
    while (<>) {
        s/$pattern/$replacement/;
        print;
    }
    unlink "$file.old";
}

stamp("ccx_$version.c", qr/You are using an executable made on.*/,
      "You are using an executable made on $date\\n\");");
stamp("ccx_${version}step.c", qr/You are using an executable made on.*/,
      "You are using an executable made on $date\\n\");");
stamp('frd.c', qr/COMPILETIME.*/,
      "COMPILETIME       $date                    \\n\",p1);");
