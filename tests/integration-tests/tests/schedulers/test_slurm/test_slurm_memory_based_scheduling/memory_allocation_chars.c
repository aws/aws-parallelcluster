#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {

    double *array;
    long int num_elem, i, total_mem;
    int sleep_time;

    if (argc > 3) {
        printf("Only two arguments (memory size and sleep time) are supported\n");
        exit(1);
    }

    total_mem = 1e8;
    sleep_time = 30;

    if (argc>=2) {
        total_mem = atol(argv[1]);
    }
    if (argc==3) {
        sleep_time = atoi(argv[2]);
    }

    printf("Memory to be allocated: %ld\n", total_mem);

    array = (double*) malloc(total_mem);
    num_elem = total_mem / (long int) sizeof(double);

    for (i = 0; i < num_elem; i++) {
        array[i] = 1.0;
    }
    sleep(sleep_time);

    if (array == NULL) {
        printf("Memory not allocated.\n");
        return 1;
    }
    else {
        printf("Memory successfully allocated.\n");
        free(array);
        printf("Memory successfully freed.\n");
    }

    return 0;
}
