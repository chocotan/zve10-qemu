#include <linux/module.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/uaccess.h>

static int show_mode(struct seq_file *m, void *v)
{
    seq_puts(m, "normal\n");
    return 0;
}
static int open_mode(struct inode *inode, struct file *file)
{
    return single_open(file, show_mode, NULL);
}
static const struct file_operations fops = {
    .owner = THIS_MODULE,
    .open = open_mode,
    .read = seq_read,
    .llseek = seq_lseek,
    .release = single_release,
};
static struct proc_dir_entry *udm, *entry;
static int __init bm_init(void)
{
    udm = proc_mkdir("udm", NULL);
    if (!udm) return -ENOMEM;
    entry = proc_create("upm_bootmode", 0444, udm, &fops);
    if (!entry) return -ENOMEM;
    printk("bootmode: /proc/udm/upm_bootmode=normal\n");
    return 0;
}
static void __exit bm_exit(void)
{
    if (entry) remove_proc_entry("upm_bootmode", udm);
    if (udm) remove_proc_entry("udm", NULL);
}
module_init(bm_init);
module_exit(bm_exit);
MODULE_LICENSE("GPL");
